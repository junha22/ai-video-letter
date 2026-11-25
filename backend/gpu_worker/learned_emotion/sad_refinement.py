"""Calibrate the final shared Sad expression against each portrait's Neutral render."""
import cv2
import numpy as np
import torch
from torch import nn

from .face_geometry import MOUTH_CONTOUR, _landmarks, polygon_self_crosses, static_mesh_workers

COMMON_FORMAT = 'float_common_sad_v1'
MOUTH_FORMAT = 'float_sad_shared_mouth_v2'
BROWS = ((70,63,107,66),(300,293,336,296))
EYES = ((33,133,159,145),(263,362,386,374))
COMMON_LIMIT = np.array([.050,.050,.045,.045,.052,.052],dtype=np.float32)


def lip_geometry(points):
    eye = points[263]-points[33]
    span = np.linalg.norm(eye)
    horizontal = eye/span
    down = np.array([-horizontal[1],horizontal[0]])
    center = points[[13,14]].mean(0)
    corners = points[[61,291]]
    levels = (corners-center)@down
    width = (corners[1]-corners[0])@horizontal
    gap = (points[14]-points[13])@down
    return center,horizontal,down,span,width,levels,gap


def smoothstep(value):
    unit = np.clip(value,0,1)
    return unit*unit*(3-2*unit)


def patch_box(frame,points,padding):
    minimum = np.maximum(np.floor(points.min(0)-padding).astype(int),0)
    maximum = np.minimum(np.ceil(points.max(0)+padding).astype(int),frame.shape[1::-1])
    return minimum,maximum


def corner_field(frame,points,displacement,opening=0.):
    """Move the visible corners with compact support in the local mouth plane."""
    center,horizontal,down,span,width,_,_ = lip_geometry(points)
    lower,upper = patch_box(frame,points[[61,291]],.15*span+4)
    x1,y1 = lower
    x2,y2 = upper
    yy,xx = np.mgrid[y1:y2,x1:x2].astype(np.float32)
    grid = np.stack((xx,yy),-1)
    local_x = (grid-center)@horizontal
    speech_guard = smoothstep((np.abs(local_x)/width-.29)/.085)
    field = np.zeros_like(xx)
    for corner,amount in zip(points[[61,291]],displacement):
        local = grid-corner
        distance = np.sqrt(((local@horizontal)/(.21*width))**2+((local@down)/(.13*span))**2)
        field += amount*(1-smoothstep((distance-.14)/.86))*speech_guard
    if opening:
        local_y = (grid-center)@down
        top,bottom = (points[[0,17]]-center)@down
        inner_gap = max((points[14]-points[13])@down,.01*span)
        side = 1-smoothstep((np.abs(local_x)/width-.15)/.19)
        rim = smoothstep((local_y-top+.065*span)/(.045*span))
        rim *= smoothstep((bottom+.065*span-local_y)/(.045*span))
        # A bounded inverse map moves the lip rims together with their texture.
        half_gap = max(.5*inner_gap,1.)
        opening = np.clip(opening,-.65*inner_gap,.60*inner_gap)
        field += .5*opening*np.clip(local_y/half_gap,-1,1)*rim*side
    sample = grid-field[...,None]*down-lower
    patch = frame[y1:y2,x1:x2]
    moved = cv2.remap(patch,sample[...,0].astype(np.float32),sample[...,1].astype(np.float32),
                      cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    output = frame.copy()
    output[y1:y2,x1:x2] = np.where((field!=0)[...,None],moved,patch)
    return output


def inputs(points):
    center,horizontal,_,span,width,levels,gap = lip_geometry(points)
    side = (points[[61,291]]-center)@horizontal
    return np.column_stack((levels/width,abs(side)/width,np.full(2,gap/width),np.full(2,width/span)))


def aperture(points):
    return np.linalg.norm(points[13]-points[14])/np.linalg.norm(points[33]-points[263])


def mouth_signature(points):
    _,_,_,span,width,levels,_ = lip_geometry(points)
    return np.r_[levels/span,aperture(points),width/span]


def shared_features(points,goal):
    return np.r_[mouth_signature(points),inputs(points)[:,1],goal*12]


class SharedMouth(nn.Module):
    def __init__(self):
        super().__init__()
        self.policy = nn.Sequential(nn.Linear(9,32),nn.SiLU(),nn.Linear(32,24),nn.SiLU(),nn.Linear(24,3))
        nn.init.zeros_(self.policy[-1].weight)
        nn.init.zeros_(self.policy[-1].bias)

    def forward(self,features):
        goal = features[...,6:]/12
        update = self.policy(features).tanh()*features.new_tensor([.012,.012,.012])
        return (goal+update).clamp(min=-.014,max=.026)


@torch.no_grad()
def fit_articulation(mesh,image,points,speech,model,target):
    before = mouth_signature(points)
    native_gap = aperture(speech)
    _,_,_,span,_,_,_ = lip_geometry(points)
    goal = np.array([target,target,np.clip(native_gap-before[2],-.013,.013)])
    controls = model(torch.as_tensor(shared_features(points,goal),dtype=torch.float32)).numpy()
    controls[:2] = np.maximum(controls[:2],target)
    expected = before+np.r_[goal,0.]
    allowed_gap_error = max(abs(before[2]-native_gap),.0025)

    def score(observed):
        if observed is None or polygon_self_crosses(observed[list(MOUTH_CONTOUR)]):
            return np.inf
        current = mouth_signature(observed)
        wrong_closure = (current[2]<.04)!=(native_gap<.04)
        gap_error = abs(current[2]-native_gap)
        return (np.mean(np.abs(current[:2]-expected[:2]))+gap_error
                +3*max(gap_error-allowed_gap_error,0.)
                +.6*abs(current[3]-before[3])+.015*wrong_closure)

    def measure(value):
        move = value*span
        return _landmarks(mesh,corner_field(image,points,move[:2],move[2]))

    # Fit the final pixels back to the same objective. This corrects detector
    # bias at the lip rim without changing the model for a specific portrait.
    best,lowest = np.zeros(3),score(points)
    for strength in (1.,.55,1.4,0.):
        trial = np.r_[np.minimum(controls[:2]*strength,.026),controls[2]]
        observed = measure(trial)
        error = score(observed)
        if error<lowest:
            best,lowest = trial.copy(),error
        if observed is None:
            continue
        gap_error = np.clip(native_gap-aperture(observed),-.009,.009)
        trial[2] = np.clip(trial[2]+1.25*gap_error,-.014,.014)
        error = score(measure(trial))
        if error<lowest:
            best,lowest = trial.copy(),error
    return best


def basis(points):
    eye_axis = points[263]-points[33]
    span = max(np.linalg.norm(eye_axis),1.)
    axis = eye_axis/span
    return axis,np.array([-axis[1],axis[0]]),span


def geometry(points):
    axis,down,span = basis(points)
    y = (points-points[1])@down/span
    x = (points-points[33])@axis/span
    brows = [y[[a,b]].mean()-y[[c,d]].mean() for a,b,c,d in BROWS]
    corners = y[[61,291]]-y[[13,14]].mean()
    opening = [np.linalg.norm(points[u]-points[l])/max(np.linalg.norm(points[a]-points[b]),1.)
               for a,b,u,l in EYES]
    return np.asarray([*brows,*corners,abs(y[14]-y[13]),*opening,
                       abs(x[291]-x[61]),abs(x[133]-x[33]),abs(x[263]-x[362]),x[1]],dtype=np.float32)


def common_geometry(points):
    _,down,span = basis(points)
    inner = [(points[[left,right]].mean(0)-points[[a,b]].mean(0))@down/span
             for (_,_,a,b),(left,right,_,_) in zip(BROWS,EYES,strict=True)]
    return np.r_[np.asarray(inner,dtype=np.float32),geometry(points)]


def deform(image,points,actions):
    """Apply a learned, tightly supported brow/outer-lip field."""
    axis,down,span = basis(points)
    centers = np.vstack([points[[107,66]].mean(0),points[[336,296]].mean(0),
                         points[[70,63]].mean(0),points[[300,293]].mean(0),points[[61,291]]])
    result = image.copy()
    middle = points[[13,14]].mean(0)
    lip_width = max(abs((points[291]-points[61])@axis),1.)
    for index,(center,action) in enumerate(zip(centers,actions,strict=True)):
        if abs(action)<1e-6:
            continue
        rx,ry = ((.23,.15) if index<2 else (.29,.18) if index<4 else (.155,.115))
        border = (rx+ry+abs(action))*span+2
        x0,y0 = np.maximum(0,np.floor(center-border).astype(int))
        x1,y1 = np.minimum(image.shape[1::-1],np.ceil(center+border).astype(int))
        if x0>=x1 or y0>=y1:
            continue
        gy,gx = np.mgrid[y0:y1,x0:x1].astype(np.float32)
        pixels = np.stack((gx,gy),axis=-1)
        rel = pixels-center
        dx,dy = rel@axis/span,rel@down/span
        mask = np.maximum(0,1-(dx/rx)**2-(dy/ry)**2)**2
        if index<4:
            lid = points[EYES[index%2][2]]
            clearance = (lid-pixels)@down/span
            mask *= np.clip((clearance-.023)/.042,0,1)**2
        else:
            side = abs((pixels-middle)@axis)/lip_width
            mask *= np.clip((side-.295)/.10,0,1)**2
        delta = span*float(action)*mask*(1 if index<2 else -1)
        sampling = pixels+delta[...,None]*down
        mapped = cv2.remap(result,sampling[...,0].astype(np.float32),sampling[...,1].astype(np.float32),
                           cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        patch = result[y0:y1,x0:x1]
        active = mask>0
        patch[active] = mapped[active]
    return result


class CommonSad(nn.Module):
    """Predict continuous, speech-aware Sad motion from measured facial geometry."""
    def __init__(self):
        super().__init__()
        self.policy = nn.Sequential(nn.Linear(19,64),nn.SiLU(),nn.Linear(64,48),nn.SiLU(),nn.Linear(48,6))
        self.register_buffer('limit',torch.tensor(COMMON_LIMIT))
        nn.init.zeros_(self.policy[-1].weight)
        nn.init.zeros_(self.policy[-1].bias)

    def forward(self,shape,goal):
        features = torch.cat((shape*3,goal*26),dim=-1)
        return self.limit*self.policy(features).tanh()


def paired_tracks(neutral,sad):
    samples = [(i,n[2],s[2]) for i,(n,s) in enumerate(zip(neutral,sad,strict=True))
               if n[2] is not None and s[2] is not None]
    if len(samples)<max(6,len(neutral)*.65):
        return np.empty(0,dtype=int)
    ids,n,s = zip(*samples)
    n,s = np.stack(n),np.stack(s)
    valid = ((abs(n[:,4]-s[:,4])<.025)&(abs(n[:,10]-s[:,10])<.14)
             &(n[:,5:7].min(1)>.13)&(s[:,5:7].min(1)>.13))
    return np.asarray(ids)[valid]


def smooth_series(data,width=9):
    half = width//2
    padded = np.pad(data,((half,half),(0,0)),mode='edge')
    return np.stack([padded[i:i+width].mean(0) for i in range(len(data))])


def align_mouth(sad,speech,model,fraction,delay):
    """Fit controls on independent frames before applying the saved timing."""
    if len(sad)!=len(speech) or not len(sad):
        raise ValueError('Sad and speech clips must have the same nonempty timeline')
    with static_mesh_workers() as measure:
        def landmarks(mesh,pair):
            image,spoken=pair
            return image,_landmarks(mesh,image),_landmarks(mesh,spoken)

        pairs = measure(landmarks,zip(sad,speech))
        usable = [points for _,points,reference in pairs if points is not None and reference is not None]
        order = np.clip(np.arange(len(pairs))-delay,0,len(pairs)-1)
        if not usable:
            return [sad[i] for i in order],False
        target = fraction*abs(np.median([mouth_signature(points)[:2].mean() for points in usable]))

        def controls(mesh,pair):
            image,points,reference = pair
            if points is None or reference is None:
                return np.zeros(3)
            return fit_articulation(mesh,image,points,reference,model,target)

        motion = np.stack(measure(controls,pairs))
    padded = np.pad(motion[:,:2],((1,1),(0,0)),mode='edge')
    motion[:,:2] = .12*padded[:-2]+.76*padded[1:-1]+.12*padded[2:]
    frames = []
    for i in order:
        image,points,reference = pairs[i]
        if points is not None and reference is not None:
            displacement = motion[i]*lip_geometry(points)[3]
            image = corner_field(image,points,displacement[:2],displacement[2])
        frames.append(image)
    return frames,True


@torch.no_grad()
def expression_controls(neutral,sad,model,profile,gap_bins):
    """Use the released face1 strength profile for the input portrait."""
    with static_mesh_workers() as map_mesh:
        def track(mesh,image):
            points = _landmarks(mesh,image)
            return image,points,geometry(points) if points is not None else None

        n = map_mesh(track,neutral)
        s = map_mesh(track,sad)
        ids = paired_tracks(n,s)
        if len(ids)<6:
            return [(image,image) for image in sad],False
        shape = np.stack([common_geometry(p) if p is not None else np.zeros(13,dtype=np.float32)
                          for _,p,_ in s])
        neutral_shape = np.stack([common_geometry(n[i][1]) for i in ids])
        profile = profile[np.digitize(neutral_shape[:,6],gap_bins)]
        target = neutral_shape[:,:6].copy()
        target[:,:2] += profile[:,0,None].clip(0,.026)
        target[:,2:4] += profile[:,1,None].clip(0,.026)
        target[:,4:6] += profile[:,2,None].clip(.004,.032)
        floor = (.75*profile[:,3]+.25*profile[:,4])[:,None]
        target[:,4:6] = np.maximum(target[:,4:6],floor)
        request = np.clip(target-shape[ids,:6],0,.033)
        time = np.arange(len(s))

        def interpolate(indices,values):
            return np.stack([np.interp(time,indices,axis) for axis in values.T],axis=1).astype(np.float32)

        goals = smooth_series(interpolate(ids,request),7)
        features = torch.from_numpy(shape)
        proposal = smooth_series(model(features,torch.from_numpy(goals)).numpy(),7)
        probes = ids[::3]
        expected = goals[probes]
        cue_weights = np.array([1.10,1.10,.75,.75,1.15,1.15])
        tolerance = np.array([.004,.020,.020,.012,.009,.009,.008])
        preserve_weights = np.array([3.,1.1,1.1,1.,.6,.6,.6])

        def measure(actions):
            def probe(mesh,i):
                rgb,points,_ = s[i]
                observed = _landmarks(mesh,deform(rgb,points,actions[i]))
                return shape[i] if observed is None else common_geometry(observed)
            return np.stack(map_mesh(probe,probes))-shape[probes]

        def objective(response):
            error = response[:,:6]-expected
            aggregate = abs(np.median(error,axis=0))
            frame_error = np.quantile(abs(error),.65,axis=0)
            excess = np.maximum(abs(response[:,6:])-tolerance,0)
            preservation = np.quantile(excess,.80,axis=0)
            return float(((.75*aggregate+.25*frame_error)*cue_weights).mean()
                         +(preservation*preserve_weights).mean())

        best = objective(np.zeros((len(probes),13))),np.zeros_like(proposal)
        for _ in range(5):
            response = measure(proposal)
            cost = objective(response)
            if cost<best[0]:
                best = cost,proposal.copy()
            remainder = interpolate(probes,expected-response[:,:6])
            correction = model(features,torch.from_numpy(smooth_series(remainder,9))).numpy()
            proposal = np.clip(proposal+.70*smooth_series(correction,9),-COMMON_LIMIT,COMMON_LIMIT)
        actions = best[1]

    return [(image,deform(image,points,action) if points is not None and action.any() else image)
            for (image,points,_),action in zip(s,actions)],True
