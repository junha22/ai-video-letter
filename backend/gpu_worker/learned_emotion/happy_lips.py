"""Preserve the native Happy articulation at FLOAT's final render composition."""
from collections import deque
from contextlib import contextmanager
from itertools import chain, repeat

import cv2
import numpy as np
import torch
from torch.nn import functional as F

from .face_geometry import MOUTH_CONTOUR, _landmarks, polygon_self_crosses


LIP_TOP = (61,40,37,0,267,270,291)
LIP_BOTTOM = (61,91,84,17,314,321,291)
INNER_TOP = (78,191,80,81,82,13,312,311,310,415,308)
INNER_BOTTOM = (78,95,88,178,87,14,317,402,318,324,308)
INNER_OUTLINE = INNER_TOP+tuple(reversed(INNER_BOTTOM[1:-1]))
LUMA = np.array([.299,.587,.114], dtype=np.float32)


def _smoothstep(value):
    t = np.clip(value,0,1)
    return t*t*(3-2*t)


def _tooth_exposure(image,points):
    if points is None:
        return None
    axis,span = _eye_basis(points)
    opening = (points[14]-points[13])@axis[:,1]/span
    if not np.isfinite(opening) or opening<=.070:
        return None

    outline = points[list(MOUTH_CONTOUR)]
    inner = points[list(INNER_OUTLINE)]
    if polygon_self_crosses(outline):
        return None
    left,top = np.maximum(np.floor(outline.min(0)).astype(int)-2,0)
    right,bottom = np.minimum(np.ceil(outline.max(0)).astype(int)+3,image.shape[1::-1])
    if right<=left or bottom<=top:
        return None
    region = (slice(top,bottom),slice(left,right))
    patch = image[region].astype(np.float32)
    shift = np.array([left,top])
    cavity = np.zeros(patch.shape[:2],dtype=np.uint8)
    outer = np.zeros_like(cavity)
    cv2.fillPoly(cavity,[np.rint(inner-shift).astype(np.int32)],1)
    cv2.fillPoly(outer,[np.rint(outline-shift).astype(np.int32)],1)
    cavity &= cv2.erode(outer,np.ones((3,3),dtype=np.uint8))

    y,x = np.mgrid[top:bottom,left:right]
    local = (np.stack((x,y),axis=-1)-points[13])@axis
    projected = (points-points[13])@axis

    def lip_height(rim):
        line = projected[list(rim)]
        line = line[np.argsort(line[:,0])]
        return np.interp(local[...,0],line[:,0],line[:,1])

    upper,lower = lip_height(INNER_TOP),lip_height(INNER_BOTTOM)
    depth = (local[...,1]-upper)/np.maximum(lower-upper,.5)
    core = cavity.astype(bool)&(depth>.08)&(depth<.72)
    if core.sum()<12:
        return None

    luma = patch@LUMA
    shadow = np.percentile(luma[cavity>0],20)
    contrast = np.maximum(luma-shadow,0)
    exposure = float(_smoothstep((np.percentile(contrast[core],88)-32)/43))
    tooth_tone = _smoothstep((62-(patch[...,0]-patch[...,2]))/29)
    enamel = _smoothstep((contrast-14)/39)*tooth_tone
    edge = _smoothstep(cv2.distanceTransform(cavity,cv2.DIST_L2,5)/2)
    upper_band = _smoothstep((.88-depth)/.30)
    gate = _smoothstep((opening-.070)/.052)
    # Compress the highlights without replacing their texture or flattening
    # the contrast that makes the individual teeth visible.
    reduction = np.minimum(27,.30*contrast)*edge*upper_band*enamel*gate
    return region,reduction,exposure


def stabilize_happy_teeth(images):
    """Yield original and adjusted RGB frames using the same render's exposure."""
    import mediapipe as mp

    weights = (1,2,3,2,1)
    padding = (None,None)
    window = deque([padding,padding],maxlen=len(weights))
    with mp.solutions.face_mesh.FaceMesh(refine_landmarks=True,max_num_faces=1) as mesh:
        measurements = ((image,_tooth_exposure(image,_landmarks(mesh,image))) for image in images)
        for entry in chain(measurements,repeat(padding,2)):
            window.append(entry)
            if len(window)<len(weights):
                continue
            image,sample = window[2]
            if image is None:
                continue
            if sample is None:
                yield image,image
                continue
            region,reduction,_ = sample
            nearby = [(weight,reading[2]) for weight,(_,reading) in zip(weights,window) if reading is not None]
            strength = sum(weight*score for weight,score in nearby)/sum(weight for weight,_ in nearby)
            drop = np.rint(reduction*strength).astype(np.int16)
            if drop.any():
                adjusted = image.copy()
                adjusted[region] = np.maximum(image[region]-drop[...,None],0).astype(np.uint8)
                yield image,adjusted
            else:
                yield image,image


def _rgb(image):
    return ((image[0].float().clamp(-1,1)+1)*127.5).byte().permute(1,2,0).cpu().numpy()


@contextmanager
def capture_rgb_inputs(layer):
    values = {}

    def capture(_module,args):
        values['shape_features'] = args[0]

    def upsample(_module,_args,output):
        values['coarse_features'] = output

    before = layer.register_forward_pre_hook(capture)
    after = layer.upsample.register_forward_hook(upsample)
    try:
        yield values
    finally:
        before.remove()
        after.remove()


def _eye_basis(points):
    eyes = points[263]-points[33]
    width = np.linalg.norm(eyes)
    x = eyes/width
    return np.stack((x,[-x[1],x[0]]),axis=1),width


def _upper_alignment(native,happy,size,device):
    native_axis,native_width = _eye_basis(native)
    happy_axis,happy_width = _eye_basis(happy)
    native_center = native[[33,263]].mean(0)
    happy_center = happy[[33,263]].mean(0)
    scale = happy_width/native_width
    forward = happy_axis@native_axis.T*scale
    transform = torch.as_tensor(forward,device=device,dtype=torch.float32)
    native_center_tensor = torch.as_tensor(native_center,device=device,dtype=torch.float32)
    happy_center_tensor = torch.as_tensor(happy_center,device=device,dtype=torch.float32)
    ticks = torch.arange(size,device=device,dtype=torch.float32)
    y,x = torch.meshgrid(ticks,ticks,indexing='ij')
    points = torch.stack((x,y),dim=-1)-native_center_tensor
    grid = points@transform.T+happy_center_tensor
    grid = (grid*2/(size-1)-1)[None]

    axes = torch.as_tensor(native_axis,device=device,dtype=torch.float32)
    local = (points@axes)/native_width
    # Keep the native pose, nose, and lower-face speech geometry. Apply the
    # learned expression around the eyes and brows in those same coordinates.
    side = ((.67-local[...,0].abs())/.17).clamp(0,1)
    top = ((local[...,1]+.48)/.15).clamp(0,1)
    bottom = ((.11-local[...,1])/.13).clamp(0,1)
    blend = side*top*bottom
    alpha = .68*blend.square()*(3-2*blend)
    return grid,alpha[None,None]


def _lip_center_alignment(native,happy,size,device,*,use_happy_teeth=None):
    native_axis,native_span = _eye_basis(native)
    happy_axis,happy_span = _eye_basis(happy)
    native_center = native[[13,14]].mean(0)
    happy_center = happy[[13,14]].mean(0)
    h = (happy-happy_center)@happy_axis
    n = (native-native_center)@native_axis
    happy_left,happy_right = h[[61,291],0]
    native_left,native_right = n[[61,291],0]
    width = happy_right-happy_left
    if (width<4 or native_right-native_left<4 or
            polygon_self_crosses(h[list(MOUTH_CONTOUR)]) or polygon_self_crosses(n[list(MOUTH_CONTOUR)])):
        return None

    def tensor(value):
        return torch.as_tensor(value,device=device,dtype=torch.float32)

    coords = torch.arange(size,device=device,dtype=torch.float32)
    y,x = torch.meshgrid(coords,coords,indexing='ij')
    local = (torch.stack((x,y),dim=-1)-tensor(happy_center))@tensor(happy_axis)
    lx,ly = local.unbind(-1)
    native_x = (lx-happy_left)*((native_right-native_left)/width)+native_left

    def contour(points,indices,at):
        line = points[list(indices)]
        line = line[np.argsort(line[:,0])]
        samples = np.linspace(line[0,0],line[-1,0],128)
        ys = tensor(np.interp(samples,line[:,0],line[:,1]))
        q = ((at-samples[0])*127/max(samples[-1]-samples[0],1e-4)).clamp(0,127)
        i = q.floor().long()
        return torch.lerp(ys[i],ys[(i+1).clamp_max(127)],q-i)

    ht,hb = (contour(h,rim,lx) for rim in (LIP_TOP,LIP_BOTTOM))
    nt,nb = (contour(n,rim,native_x) for rim in (LIP_TOP,LIP_BOTTOM))
    ni_t = contour(n,INNER_TOP,native_x).clamp(min=nt,max=torch.maximum(nt,nb))
    ni_b = torch.maximum(ni_t,contour(n,INNER_BOTTOM,native_x).clamp(min=nt,max=torch.maximum(nt,nb)))
    valid = (hb-ht>.5)&(nb-nt>.5)
    # Match the audio-driven cavity height on the target face, reserving
    # lip tissue on both sides. Map all three vertical bands monotonically.
    rim = torch.minimum(.18*(hb-ht).clamp_min(0),torch.full_like(ht,.016*happy_span))
    inner_top,max_bottom = ht+rim,torch.maximum(ht+rim,hb-rim)
    scale_y = happy_span/native_span
    gap = torch.minimum((ni_b-ni_t)*scale_y,max_bottom-inner_top)
    def band(a,b,u,v):
        t = ((ly-a)/(b-a).clamp_min(.15)).clamp(0,1)
        return torch.lerp(u,v,t)

    if use_happy_teeth is None:
        open_native = n[14,1]-n[13,1]>.04*native_span
        has_happy_cavity = h[14,1]-h[13,1]>.018*happy_span
        use_happy_teeth = not open_native or has_happy_cavity

    if use_happy_teeth:
        # Keep the existing Happy upper lip and its visible teeth together.
        # Move the lower lip for the speech opening and absorb height
        # changes in the lower part of the cavity.
        hi_t = contour(h,INNER_TOP,lx).clamp(min=ht,max=torch.maximum(ht,hb))
        hi_b = torch.maximum(hi_t,contour(h,INNER_BOTTOM,lx).clamp(min=ht,max=torch.maximum(ht,hb)))
        ti_t = hi_t.clamp(min=inner_top,max=max_bottom-gap)
        ti_b = ti_t+gap
        teeth_height = .58*torch.minimum(hi_b-hi_t,gap)
        cavity = torch.where(
            ly<=ti_t+teeth_height,hi_t+(ly-ti_t),
            band(ti_t+teeth_height,ti_b,hi_t+teeth_height,hi_b))
        sampled_y = torch.where(ly<ti_t,band(ht,ti_t,ht,hi_t),
                                torch.where(ly>ti_b,band(ti_b,hb,hi_b,hb),cavity))
        sample_xy = torch.stack((lx,sampled_y),dim=-1)@tensor(happy_axis.T)+tensor(happy_center)
    else:
        # At an onset with no visible Happy cavity, use the matching
        # frame's native mouth interior instead of stretching a lip line.
        centre = ((ni_t+ni_b)*(.5*scale_y)).clamp(min=inner_top+gap/2,max=max_bottom-gap/2)
        ti_t,ti_b = centre-gap/2,centre+gap/2
        sampled_y = torch.where(
            ly<ti_t,band(ht,ti_t,nt,ni_t),
            torch.where(ly>ti_b,band(ti_b,hb,ni_b,nb),band(ti_t,ti_b,ni_t,ni_b)))
        sample_xy = torch.stack((native_x,sampled_y),dim=-1)@tensor(native_axis.T)+tensor(native_center)
    grid = (sample_xy*2/(size-1)-1)[None]
    horizontal = torch.minimum(lx-happy_left,happy_right-lx)
    side = ((horizontal-.08*width)/(.16*width)).clamp(0,1)
    # Exactly zero outside the original outer lip outline. The last colour
    # projection is pointwise, so mouth texture cannot travel past this mask.
    inside = torch.minimum(ly-ht,hb-ly)
    outline = np.zeros((size,size),dtype=np.uint8)
    cv2.fillPoly(outline,[np.rint(happy[list(MOUTH_CONTOUR)]).astype(np.int32)],1)
    outline = cv2.erode(outline,np.ones((3,3),dtype=np.uint8),iterations=1)
    blend = side*(inside/1.6).clamp(0,1)*valid*tensor(outline)
    return grid,(blend.square()*(3-2*blend))[None,None],use_happy_teeth


def _compose(layer,native,happy,native_landmarks,happy_landmarks,*,preserve_corners=False,base_rgb=None):
    shape = native['shape_features']
    size = shape.shape[-1]
    if preserve_corners:
        mapping = _lip_center_alignment(native_landmarks,happy_landmarks,size,shape.device)
        if mapping is None:
            return None
        grid,alpha,use_happy_teeth = mapping
        primary,secondary = happy,happy if use_happy_teeth else native
    else:
        grid,alpha = _upper_alignment(native_landmarks,happy_landmarks,size,shape.device)
        primary,secondary = native,happy

    def blend(key):
        patch = F.grid_sample(secondary[key].float(),grid,mode='bilinear',
                              padding_mode='border',align_corners=True)
        return torch.lerp(primary[key],patch.to(primary[key]),alpha.to(primary[key]))

    composed = layer.conv(blend('shape_features'))+layer.bias+blend('coarse_features')
    if preserve_corners:
        composed = torch.where(alpha>0,composed,base_rgb)
    return composed


@torch.no_grad()
def render_happy(model,appearance,features,speech,expressive,emotion,repair,*,speech_appearance,speech_features,
                 preserve_corners=False):
    import mediapipe as mp

    decoder = model.motion_autoencoder.dec
    final_rgb = decoder.to_rgbs[-1]
    labels = torch.tensor([3],device=speech.device)
    if speech.shape!=expressive.shape:
        raise ValueError('Native and learned Happy motion must have the same timeline')
    frames = []
    with mp.solutions.face_mesh.FaceMesh(refine_landmarks=True,max_num_faces=1) as native_mesh, \
            mp.solutions.face_mesh.FaceMesh(refine_landmarks=True,max_num_faces=1) as happy_mesh:
        for start in range(0,speech.shape[1],3):
            base_motion = speech[0,start:start+3]
            count = len(base_motion)
            expanded = [value.expand(count,*value.shape[1:]).contiguous() for value in speech_features]
            with (torch.backends.cudnn.flags(benchmark=False,deterministic=True,allow_tf32=False),
                  emotion.teacher(),repair.disabled(),capture_rgb_inputs(final_rgb) as native):
                base_images,_ = decoder(speech_appearance+base_motion,alpha=None,feats=expanded)
            for j,current in enumerate(expressive[0,start:start+count]):
                native_rgb = base_images[j:j+1]
                native_frame = {key:value[j:j+1] for key,value in native.items()}
                with emotion.renderer_condition(labels),repair.condition(labels),capture_rgb_inputs(final_rgb) as happy:
                    happy_rgb,_ = decoder(appearance+current,alpha=None,feats=features)
                a = _landmarks(native_mesh,_rgb(native_rgb))
                b = _landmarks(happy_mesh,_rgb(happy_rgb))
                if a is None or b is None:
                    frames.append((happy_rgb if preserve_corners else native_rgb)[0].cpu())
                    continue
                with torch.backends.cudnn.flags(benchmark=False,deterministic=True,allow_tf32=False):
                    composed = _compose(final_rgb,native_frame,happy,a,b,preserve_corners=preserve_corners,
                                        base_rgb=happy_rgb)
                    frames.append((happy_rgb if composed is None else composed)[0].cpu())
    if preserve_corners:
        for index,(original,image) in enumerate(stabilize_happy_teeth(_rgb(frame[None]) for frame in frames)):
            if image is not original:
                delta = image.astype(np.int16)-original
                frames[index] = frames[index]+torch.from_numpy(delta).permute(2,0,1).float()/127.5
    return torch.stack(frames)
