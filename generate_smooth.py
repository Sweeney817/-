from pathlib import Path
import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
W,H=256,208
STATES=('litter','drink','stretch','loaf','roll','scratch')

def prep(a):
    rgb=a[:,:,:3].astype(np.float32)
    alpha=a[:,:,3:4].astype(np.float32)/255
    # Silhouette and texture both contribute to optical flow.
    gray=cv2.cvtColor((rgb*alpha + 255*(1-alpha)).astype(np.uint8),cv2.COLOR_RGB2GRAY)
    return gray

def tween(a,b,amount,forward,backward):
    y,x=np.mgrid[0:H,0:W].astype(np.float32)
    def warp(img,flow,scale):
        v=img.astype(np.float32)/255
        v[:,:,:3] *= v[:,:,3:4]
        return cv2.remap(v,x-flow[:,:,0]*scale,y-flow[:,:,1]*scale,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    wa=warp(a,forward,amount); wb=warp(b,backward,1-amount)
    mix=wa if amount < 0.5 else wb
    alpha=mix[:,:,3:4]
    out=np.zeros_like(mix)
    out[:,:,:3]=np.divide(mix[:,:,:3],alpha,out=np.zeros_like(mix[:,:,:3]),where=alpha>0.001)
    out[:,:,3:4]=alpha
    return np.uint8(np.clip(out*255,0,255))

for state in STATES:
    atlas=np.array(Image.open(ROOT/'assets'/f'{state}_sequence.png').convert('RGBA'))
    frames=[atlas[:,i*W:(i+1)*W,:].copy() for i in range(8)]
    output=[]
    for a,b in zip(frames,frames[1:]):
        output.append(a)
        ga,gb=prep(a),prep(b)
        f=cv2.calcOpticalFlowFarneback(ga,gb,None,0.5,4,25,4,7,1.5,0)
        rev=cv2.calcOpticalFlowFarneback(gb,ga,None,0.5,4,25,4,7,1.5,0)
        for t in (.25,.5,.75): output.append(tween(a,b,t,f,rev))
    output.append(frames[-1])
    Image.fromarray(np.concatenate(output,axis=1)).save(ROOT/'assets'/f'{state}_smooth.png',optimize=True)
    print(state,len(output),flush=True)

