"""Causal continuation of FLOAT motion at a quiet ending."""
import numpy as np
import soundfile as sf
import torch
from torch import nn


FORMAT = 'float_learned_ending_motion_v1'
HISTORY = 10
HORIZON = 7


def audio_levels(path,frames):
    samples,rate = sf.read(str(path),dtype='float32',always_2d=True)
    mono = samples.mean(1)
    levels = np.zeros(frames,dtype=np.float32)
    for i in range(frames):
        segment = mono[round(i*rate/25):round((i+1)*rate/25)]
        if len(segment):
            levels[i] = np.sqrt(np.mean(np.square(segment)))
    return levels/max(np.quantile(levels,.75),.004)


class EndingMotion(nn.Module):
    def __init__(self,scale):
        super().__init__()
        self.register_buffer('scale',torch.as_tensor(scale).float().clamp_min(.1))
        self.context = nn.Sequential(nn.Linear(HISTORY*20+HISTORY+HORIZON,128),nn.SiLU(),
                                     nn.Linear(128,96),nn.SiLU())
        self.attention = nn.Linear(96,HORIZON*HISTORY)
        self.change = nn.Linear(96,HORIZON*20)
        self.register_buffer('recent',torch.linspace(-4.,2.,HISTORY))
        nn.init.zeros_(self.attention.weight)
        nn.init.zeros_(self.attention.bias)
        nn.init.zeros_(self.change.weight)
        nn.init.zeros_(self.change.bias)

    def forward(self,past,levels):
        relative = (past-past[:,-1:])/self.scale
        state = self.context(torch.cat((relative.flatten(1),levels.clamp(0,4).log1p()),1))
        weights = (self.attention(state).reshape(-1,HORIZON,HISTORY)+self.recent).softmax(-1)
        adjustment = .22*self.change(state).reshape(-1,HORIZON,20).tanh()*self.scale
        return weights,adjustment

    def predict(self,past,levels):
        weights,adjustment = self(past,levels)
        return weights@past+adjustment

    @torch.no_grad()
    def continue_motion(self,motion,directions,audio_path):
        if motion.ndim!=3 or len(motion)!=1:
            raise ValueError('The ending motion adapter expects one clip at a time')
        count = motion.shape[1]
        if count<HISTORY+HORIZON:
            return motion
        levels = audio_levels(audio_path,count)
        start = count-HORIZON
        if np.max(levels[start:])>.23:
            return motion
        past = motion[:,start-HISTORY:start].float()
        audio = torch.as_tensor(levels[start-HISTORY:],device=past.device)[None]
        weights,adjustment = self(past@directions,audio)
        forecast = weights@past+adjustment@directions.T
        return torch.cat((motion[:,:start],forecast.to(motion)),dim=1)


def load_ending(path,device):
    saved = torch.load(path,map_location='cpu',weights_only=True)
    if saved['format']!=FORMAT:
        raise ValueError('Unexpected FLOAT ending motion checkpoint')
    model = EndingMotion(saved['weights']['scale'])
    model.load_state_dict(saved['weights'])
    return model.to(device).eval().requires_grad_(False)
