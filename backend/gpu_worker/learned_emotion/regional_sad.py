"""Apply the learned regional offsets inside FLOAT's final decoder flows."""
from contextlib import contextmanager

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .face_geometry import _landmarks


@contextmanager
def condition_source_flow(decoder,field,*,support=None):
    """Compose a local displacement with FLOAT's final source-feature grid."""
    flow = decoder.to_flows[-1]
    incoming = None

    def capture(_layer,inputs):
        nonlocal incoming
        incoming = inputs[3] if len(inputs)>3 else None

    def apply(_layer,_inputs,values):
        size = values.shape[-1]
        shift = field(size)
        prior = values.float()+flow.bias.float()
        if incoming is not None:
            prior = prior+flow.upsample(incoming).float()
        ticks = torch.linspace(-1,1,size,device=values.device)
        y,x = torch.meshgrid(ticks,ticks,indexing='ij')
        identity = torch.stack((x,y),dim=0)[None]
        sample_at = (identity-shift*(2/(size-1))).permute(0,2,3,1)
        base_grid = identity+prior[:,:2].tanh()
        warped = F.grid_sample(base_grid,sample_at,padding_mode='border',align_corners=True)
        new_logits = (warped-identity).clamp(-.9999,.9999).atanh()
        active = shift.abs().amax(1,keepdim=True)>0 if support is None else support
        delta = (new_logits-prior[:,:2])*active
        return torch.cat((values[:,:2]+delta.to(values),values[:,2:]),dim=1)

    holder = flow.register_forward_pre_hook(capture)
    handle = flow.conv.register_forward_hook(apply)
    try:
        yield
    finally:
        handle.remove()
        holder.remove()


@contextmanager
def condition_contour(decoder,shift,*,support=None):
    """Keep the high-resolution flow and the coarse render in the same geometry."""
    active = shift.abs().amax(1,keepdim=True)>0 if support is None else support
    def pull_skip(_module,_inputs,features):
        size = features.shape[-1]
        ticks = torch.linspace(-1,1,size,device=features.device)
        y,x = torch.meshgrid(ticks,ticks,indexing='ij')
        grid = torch.stack((x,y),dim=-1)[None]-shift.permute(0,2,3,1)*(2/(size-1))
        moved = F.grid_sample(features.float(),grid,padding_mode='border',align_corners=True)
        return torch.where(active,moved.to(features),features)

    handle = decoder.to_rgbs[-1].upsample.register_forward_hook(pull_skip)
    try:
        with condition_source_flow(decoder,lambda _:shift,support=active):
            yield
    finally:
        handle.remove()


class RegionalSadFlow(nn.Module):
    def __init__(self,decoder,alpha_std,*,strong=False,trajectory=False,detail=False,corner_residual=False):
        super().__init__()
        if corner_residual and not (trajectory and detail):
            raise ValueError('Corner-only learning requires the detailed trajectory renderer')
        self.limit = .04 if trajectory else .14 if strong else .08
        self.trajectory = trajectory
        self.regions = 8 if detail else 6
        context = 7 if strong else 5
        self.register_buffer('alpha_std',alpha_std.float().clamp_min(.20))
        # Keeping edits in the last ToFlow avoids propagation through pyramid
        # convolutions. The following ToRGB convolution is pointwise.
        object.__setattr__(self,'flow',decoder.to_flows[-1].conv)
        object.__setattr__(self,'decoder',decoder)
        self.motion = nn.Sequential(nn.Conv1d(40,32,context,padding=context//2),nn.SiLU(),
                                    nn.Conv1d(32,24,context,padding=context//2),nn.SiLU(),
                                    nn.Conv1d(24,2*self.regions,1))
        nn.init.zeros_(self.motion[-1].weight)
        nn.init.zeros_(self.motion[-1].bias)
        self.corner_head = nn.Conv1d(24,2,1) if corner_residual else None
        if self.corner_head is not None:
            nn.init.zeros_(self.corner_head.weight)
            nn.init.constant_(self.corner_head.bias,-1.5)

    def forward(self,speech,reference,*,apply_corner_residual=True):
        relative = (speech-reference)/self.alpha_std
        context = torch.cat((relative,(reference/self.alpha_std).expand_as(relative)),dim=-1)
        features = context.T[None]
        if self.corner_head is None:
            regions = self.motion(features)[0].T.reshape(-1,self.regions,2)
            return (self.limit*regions.tanh(),)
        for layer in list(self.motion)[:-1]:
            features = layer(features)
        regions = self.motion[-1](features)[0].T.reshape(-1,self.regions,2)
        offsets = self.limit*regions.tanh()
        if apply_corner_residual:
            # About 1.4 pixels at 512px. Preserve the existing horizontal,
            # central-lip and eye coefficients.
            offsets = offsets.clone()
            offsets[:,4:6,1] = offsets[:,4:6,1]+.0055*self.corner_head(features)[0].T.sigmoid()
        return (offsets,)

    @contextmanager
    def condition(self,offsets,*,regions):
        if self.trajectory:
            shift = torch.einsum('brc,brhw->bchw',offsets[0].float(),regions)
            shift = shift*(regions.shape[-1]*.5)
            with condition_contour(self.decoder,shift,support=regions.amax(1,keepdim=True)>0):
                yield
            return

        def add_flow(_module,_inputs,output):
            # Channels are the existing ToFlow x/y sampling logits. Use the
            # native mask channel as-is and let ToFlow render its own features.
            if output.shape[-2:]!=regions.shape[-2:]:
                raise ValueError('Region grid must match the final ToFlow resolution')
            delta = torch.einsum('brc,brhw->bchw',offsets[0].float(),regions)
            return torch.cat((output[:,:2]+delta.to(output),output[:,2:]),dim=1)

        handle = self.flow.register_forward_hook(add_flow)
        try:
            yield
        finally:
            handle.remove()


def face_regions(frames,mesh,*,strong=False,trajectory=False,detail=False):
    """Track the base render and leave the iris, inner lips and jaw protected."""
    height,width = frames.shape[-2:]
    if height!=width:
        raise ValueError('Expected square FLOAT frames')
    rgb = ((frames.float().clamp(-1,1)+1)*127.5).byte().permute(0,2,3,1).cpu().numpy()
    tracked = [_landmarks(mesh,np.ascontiguousarray(image)) for image in rgb]
    valid = [p is not None and len(p)>=478 for p in tracked]
    fallback = np.zeros((478,2),dtype=np.float32)
    points = torch.as_tensor(np.stack([p[:478] if ok else fallback
                                      for p,ok in zip(tracked,valid)]),
                             device=frames.device,dtype=torch.float32)
    grid = torch.arange(width,device=frames.device,dtype=torch.float32)
    scale = (points[:,33]-points[:,263]).norm(dim=1).clamp_min(16)

    def ellipse(center,rx,ry):
        x = (grid[None,None,:]-center[:,0,None,None])/rx[:,None,None]
        y = (grid[None,:,None]-center[:,1,None,None])/ry[:,None,None]
        return (1-x.square()-y.square()).clamp(0,1).square()

    def guard(center,rx,ry):
        x = (grid[None,None,:]-center[:,0,None,None])/rx[:,None,None]
        y = (grid[None,:,None]-center[:,1,None,None])/ry[:,None,None]
        return ((x.square()+y.square()-1)/.42).clamp(0,1)

    masks = []
    for brow,eye_top,eye_bottom,eye_corners,iris in (
            ((70,63,105,66,107),159,145,(33,133),468),
            ((336,296,334,293,300),386,374,(263,362),473)):
        opening = (points[:,eye_top]-points[:,eye_bottom]).norm(dim=1)
        eye_width = (points[:,eye_corners[0]]-points[:,eye_corners[1]]).norm(dim=1).clamp_min(1)
        radius = (points[:,iris+1:iris+5]-points[:,iris,None]).norm(dim=-1).amax(1).clamp_min(1)
        iris_guard = guard(points[:,iris],radius+2,radius+2)
        brow_center = points[:,list(brow)].mean(1)
        brow_mask = ellipse(brow_center,(.29 if strong else .23)*scale,(.13 if strong else .11)*scale)
        upper_lid = ellipse(points[:,eye_top],.19*scale,.072*scale)
        blink_guard = ((opening/eye_width-.12)/.08).clamp(0,1)
        if detail:
            outer = points[:,eye_corners[0]]
            outer_lid = ellipse(outer,.125*scale,.105*scale)*iris_guard*blink_guard[:,None,None]
            masks.extend((brow_mask*iris_guard,outer_lid))
        else:
            lid_strength = 0 if trajectory else .20 if strong else 1
            masks.extend((brow_mask*iris_guard,upper_lid*iris_guard*blink_guard[:,None,None]*lid_strength))

    lip_mid = points[:,[13,14]].mean(1)
    lip_width = (points[:,291]-points[:,61]).norm(dim=1).clamp_min(1)
    lip_gap = (points[:,13]-points[:,14]).norm(dim=1)
    inside = guard(lip_mid,.34*lip_width+1,.75*lip_gap+.05*scale)
    for corner in (61,291):
        masks.append(ellipse(points[:,corner],(.15 if strong else .125)*scale,.105*scale)*inside)
    if detail:
        # The outer lip rim has room to change thickness and curvature. Keep
        # the interior opening region protected as the audio controls it.
        inner = guard(lip_mid,.29*lip_width+1,.52*lip_gap+.018*scale)
        for edge in (17,0):
            masks.append(ellipse(points[:,edge],.32*lip_width,.050*scale)*inner)

    reliability = torch.as_tensor(valid,device=frames.device)[:,None,None,None]
    return torch.stack(masks,dim=1)*reliability
