"""Finite cup and cut-side closure derived from the container dimensions.

The cut cross-section is offset inward by wall thickness using intersections of
parallel edge lines. Separate outer/inner extrusion rings form a hollow cup.
Vertices use the supplied distribution's eight-decimal OBJ precision, but the
mesh is built directly in memory and imports no simulator implementation.
"""
import math
from pathlib import Path
import tempfile
import numpy as np
import pybullet as p


def _inset(polygon, thickness):
    points=np.asarray(polygon,dtype=np.float64)
    edges=np.roll(points,-1,axis=0)-points
    normals=np.stack((-edges[:,1],edges[:,0]),axis=1)
    normals/=np.linalg.norm(normals,axis=1)[:,None]
    intercept=np.sum(normals*points,axis=1)+thickness
    return np.asarray([np.linalg.solve(normals[[i-1,i]],intercept[[i-1,i]]) for i in range(len(points))])


def _cap(ring,reverse=False):
    return [(ring[0],ring[i+1],ring[i]) if reverse else (ring[0],ring[i],ring[i+1])
            for i in range(1,len(ring)-1)]


def _join(first,second,reverse=False,alternate_first=False):
    triangles=[]
    for i in range(len(first)):
        j=(i+1)%len(first)
        if alternate_first and i==0:
            pair=[(first[i],first[j],second[i]),(second[i],first[j],second[j])]
        else:
            pair=[(first[i],first[j],second[j]),(first[i],second[j],second[i])]
        triangles.extend(tuple(reversed(face)) if reverse else face for face in pair)
    return triangles


def container_meshes(container):
    length,width,height=(float(container[key]) for key in ('length','width','height'))
    thickness=float(container['thickness'])
    cut_x,cut_z=float(container['cut_x']),float(container['cut_y'])
    outer=np.asarray([(cut_x,0.),(length,0.),(length,height),(0.,height),(0.,cut_z)])
    inner=_inset(outer,thickness)
    shift=np.asarray([length/2,height/2])
    vertices=[]
    for section,depth in ((outer,-width/2),(outer,width/2),
                          (inner,-width/2+thickness),(inner,width/2)):
        vertices.extend([[float(x),float(z),depth] for x,z in section-shift])
    rings=[list(range(i*5,(i+1)*5)) for i in range(4)]
    triangles=(_cap(rings[0],True)+_join(rings[0],rings[1])+_cap(rings[2])+
               _join(rings[2],rings[3],True)+_join(rings[1],rings[3]))
    cup=(np.round(vertices,8).tolist(),np.asarray(triangles,dtype=np.int32).ravel().tolist())
    closure=np.asarray([(cut_x,0.),(cut_x,height),(0.,height),(0.,cut_z)])-shift
    lid_vertices=[[float(x),float(z),depth] for depth in (width/2,width/2+thickness) for x,z in closure]
    front,back=list(range(4)),list(range(4,8))
    lid_triangles=_cap(front,True)+_cap(back)+_join(front,back,alternate_first=True)
    lid=(np.round(lid_vertices,8).tolist(),np.asarray(lid_triangles,dtype=np.int32).ravel().tolist())
    return cup,lid


def build_container(client,container,via_obj=False):
    center=container.get('center',[0.,0.,float(container['height'])/2])
    orientation=p.getQuaternionFromEuler([math.pi/2,0.,0.])
    bodies=[]
    for vertices,indices in container_meshes(container):
        if via_obj:
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'mesh.obj'
                path.write_text(''.join('v '+' '.join(f'{v:.8f}' for v in vertex)+'\n' for vertex in vertices)+
                    ''.join('f '+' '.join(str(v+1) for v in indices[i:i+3])+'\n' for i in range(0,len(indices),3)))
                shape=client.createCollisionShape(p.GEOM_MESH,fileName=str(path),meshScale=[1,1,1],
                    flags=p.GEOM_FORCE_CONCAVE_TRIMESH)
        else:
            shape=client.createCollisionShape(p.GEOM_MESH,vertices=vertices,indices=indices,
                                               flags=p.GEOM_FORCE_CONCAVE_TRIMESH)
        body=client.createMultiBody(baseMass=0.,baseCollisionShapeIndex=shape,
                                    basePosition=center,baseOrientation=orientation)
        client.changeDynamics(body,-1,lateralFriction=.8,rollingFriction=.01,spinningFriction=.01)
        bodies.append(body)
    return bodies
