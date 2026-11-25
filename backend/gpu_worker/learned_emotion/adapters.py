"""Conditional LoRA inside FLOAT, without output warps or expression templates.

The old lip adapter is merged before installation and remains frozen. Neutral
and unconditioned calls bypass every new adapter, including after optimization.
"""
from __future__ import annotations

from contextlib import contextmanager
import types

import torch
from torch import nn
from torch.nn import functional as F

FORMAT = 'float_sequence_and_renderer_lora_v1'
EMOTIONS = ('happy', 'sad')


class LowRank(nn.Module):
    def __init__(self, inputs, outputs, rank):
        super().__init__()
        self.A = nn.Parameter(torch.randn(rank, inputs) * .01)
        self.B = nn.Parameter(torch.zeros(outputs, rank))

    def forward(self, x):
        return F.linear(F.linear(x, self.A), self.B)


class ConditionalLinear(nn.Module):
    def __init__(self, base, adapters, bank, scope):
        super().__init__()
        self.base = base.requires_grad_(False)
        self.adapters = adapters
        # Do not register a parent module inside its child.
        object.__setattr__(self, 'bank', bank)
        self.scope = scope

    def forward(self, x):
        result = self.base(x)
        gate = getattr(self.bank, self.scope + '_gate') if self.bank.enabled else None
        if gate is None or not bool(gate.any()):
            return result
        if len(gate) != len(x):
            raise ValueError('Emotion conditioning and feature batches differ')
        for index, name in enumerate(EMOTIONS):
            weights = gate[:, index].to(x)
            if bool(weights.any()):
                shape = (len(x),) + (1,) * (x.ndim - 1)
                result = result + self.adapters[name](x) * weights.view(shape)
        return result


class EmotionBank(nn.Module):
    def __init__(self, rank=8):
        super().__init__()
        self.rank = rank
        self.adapters = nn.ModuleDict()
        self.targets = []
        self.enabled = True
        self.motion_gate = self.renderer_gate = None

    @contextmanager
    def teacher(self):
        enabled = self.enabled
        self.enabled = False
        try:
            yield
        finally:
            self.enabled = enabled

    @contextmanager
    def renderer_condition(self, labels):
        previous = self.renderer_gate
        labels = torch.as_tensor(labels)
        self.renderer_gate = torch.stack((labels == 3, labels == 5), -1).float()
        try:
            yield
        finally:
            self.renderer_gate = previous

    def add(self, model, name, scope):
        base = model.get_submodule(name)
        if base.weight.ndim != 2:
            raise ValueError(f'Expected a linear modulation: {name}')
        outputs, inputs = base.weight.shape
        branches = nn.ModuleDict({e: LowRank(inputs, outputs, self.rank) for e in EMOTIONS}).to(base.weight.device)
        key = f'{scope}_{len(self.targets):03d}'
        self.adapters[key] = branches
        self.targets.append({'key': key, 'name': name, 'scope': scope})
        parent, attribute = name.rsplit('.', 1)
        setattr(model.get_submodule(parent), attribute, ConditionalLinear(base, branches, self, scope))

    def export(self):
        return {'format': FORMAT, 'rank': self.rank, 'targets': self.targets,
                'weights': {k: v.detach().cpu().clone() for k, v in self.state_dict().items()}}

    def restore(self, saved):
        if saved['format'] != FORMAT or saved['rank'] != self.rank or saved['targets'] != self.targets:
            raise ValueError('Incompatible sequence/renderer adapter architecture')
        self.load_state_dict(saved['weights'], strict=True)


def install(G, rank=8):
    """Adapt attention, MLPs, conditioning and native decoder style modulation.

    Decoder adapters operate on whole feature maps through learned style
    modulation. No eye masks, gaze projection or RGB compositing are involved.
    """
    if any(p.requires_grad for p in G.parameters()):
        raise ValueError('Freeze and merge the original lip model before installing emotion adapters')
    bank = EmotionBank(rank)
    names = ['fmt.c_embedder']
    for i in range(len(G.fmt.blocks)):
        names.extend(f'fmt.blocks.{i}.{part}' for part in
                     ('attn.qkv', 'attn.proj', 'mlp.fc1', 'mlp.fc2'))
    for name in names:
        bank.add(G, name, 'motion')
    # All native flow scales are learnable; no spatial region is prescribed.
    for i in range(len(G.motion_autoencoder.dec.to_flows)):
        bank.add(G, f'motion_autoencoder.dec.to_flows.{i}.conv.modulation', 'renderer')
    original_forward = G.fmt.forward

    def conditioned_forward(this, t, x, wa, wr, we, prev_x=None, prev_wa=None, train=True, **kwargs):
        old = bank.motion_gate
        # Explicit dropout is handled by the training caller. FLOAT's built-in
        # dropout mutates conditions in-place and is deliberately not invoked.
        bank.motion_gate = we[:, 0, [3, 5]].float()
        try:
            return original_forward(t, x, wa, wr, we, prev_x, prev_wa, train=False, **kwargs)
        finally:
            bank.motion_gate = old

    G.fmt.forward = types.MethodType(conditioned_forward, G.fmt)
    return bank



class RepairLinear(nn.Module):
    def __init__(self,base,branches,bank):
        super().__init__();self.base=base;self.branches=branches
        object.__setattr__(self,'bank',bank)
    def forward(self,x):
        y=self.base(x)
        if self.bank.enabled and self.bank.labels is not None:
            for label,name in ((3,'happy'),(4,'neutral')):
                gate=(self.bank.labels==label).to(x)
                if bool(gate.any()):y=y+self.branches[name](x)*gate[:,None]
        return y


class DecoderRepair(nn.Module):
    def __init__(self,G,rank=4):
        super().__init__();self.rank=rank;self.enabled=True;self.labels=None
        self.adapters=nn.ModuleDict();self.targets=[]
        for i in range(len(G.motion_autoencoder.dec.to_flows)):
            name=f'motion_autoencoder.dec.to_flows.{i}.conv.modulation'
            original=G.get_submodule(name)
            outputs,inputs=original.base.weight.shape
            branches=nn.ModuleDict({e:LowRank(inputs,outputs,rank) for e in ('happy','neutral')}).to(original.base.weight.device)
            key=f'flow_{i}'
            self.adapters[key]=branches;self.targets.append(name)
            parent,attribute=name.rsplit('.',1)
            setattr(G.get_submodule(parent),attribute,RepairLinear(original,branches,self))
    @contextmanager
    def condition(self,labels):
        old=self.labels;self.labels=labels
        try:yield
        finally:self.labels=old
    @contextmanager
    def disabled(self):
        old=self.enabled;self.enabled=False
        try:yield
        finally:self.enabled=old
    def export(self):
        return {'rank':self.rank,'targets':self.targets,'weights':{k:v.detach().cpu().clone() for k,v in self.state_dict().items()}}
    def restore(self,state):
        if state['rank']!=self.rank or state['targets']!=self.targets:raise ValueError('Repair architecture differs')
        self.load_state_dict(state['weights'])
