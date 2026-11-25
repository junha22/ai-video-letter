"""Landmark measurements used by the trained emotion renderers."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
import os

import numpy as np

MOUTH_CONTOUR = (61,40,37,0,267,270,291,321,314,17,84,91)


def polygon_self_crosses(points):
    """Detect proper crossings of nonadjacent boundary edges, not closed lids."""
    p=np.asarray(points,dtype=np.float64)
    if p.ndim!=2 or p.shape[1]!=2 or len(p)<4 or not np.isfinite(p).all():
        return None
    def cross(a,b,c):
        u,v=b-a,c-a
        return float(u[0]*v[1]-u[1]*v[0])
    for i in range(len(p)):
        for j in range(i+1,len(p)):
            if j==i+1 or (i==0 and j==len(p)-1):continue
            a,b=p[i],p[(i+1)%len(p)];c,d=p[j],p[(j+1)%len(p)]
            x1,x2,x3,x4=cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)
            if x1*x2 < -1e-12 and x3*x4 < -1e-12:return True
    return False


def _landmarks(mesh,rgb):
    result=mesh.process(rgb)
    if not result.multi_face_landmarks:return None
    height,width=rgb.shape[:2]
    return np.asarray([[p.x*width,p.y*height] for p in result.multi_face_landmarks[0].landmark],dtype=np.float64)


@contextmanager
def static_mesh_workers():
    """Map independent image measurements in order, with one graph per worker."""
    import mediapipe as mp

    workers = min(4,os.cpu_count() or 1)
    with ExitStack() as stack:
        meshes = [stack.enter_context(mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,refine_landmarks=True,max_num_faces=1)) for _ in range(workers)]
        executor = stack.enter_context(ThreadPoolExecutor(max_workers=workers))

        def ordered_map(operation,items):
            items = list(items)
            block = max(1,(len(items)+workers-1)//workers)
            chunks = [items[start:start+block] for start in range(0,len(items),block)]

            def measure(chunk,mesh):
                return [operation(mesh,item) for item in chunk]

            return [value for result in executor.map(measure,chunks,meshes) for value in result]

        yield ordered_map
