import numpy as np
SR=16000
def repeats(x, win=0.05, hop=0.025, lo=0.02, hi=0.3, thr=0.9, min_rms=0.01):
    w=int(win*SR); h=int(hop*SR); out=[]
    for t in range(int(hi*SR), len(x)-w, h):
        a=x[t:t+w]
        ea=np.sqrt(np.mean(a**2))
        if ea<min_rms: continue
        best=(0,0)
        for lag in range(int(lo*SR), int(hi*SR)+1, 8):
            b=x[t-lag:t-lag+w]
            eb=np.sqrt(np.mean(b**2))
            if eb<min_rms: continue
            c=float(np.dot(a,b)/(len(a)*ea*eb))
            if c>best[0] and 0.7<ea/eb<1.4: best=(c,lag)
        if best[0]>thr: out.append((t/SR,best[0],best[1]/SR))
    return out
def clicks(x, thr_ratio=10, min_jump=0.15):
    d=np.abs(np.diff(x))
    k=int(0.005*SR)
    # local median of |d| over +-5ms via strided approx
    from scipy.ndimage import median_filter
    med=median_filter(d, size=2*k+1, mode='nearest')+1e-4
    idx=np.where((d>min_jump)&(d/med>thr_ratio))[0]
    return [(i/SR,float(d[i]),float(d[i]/med[i])) for i in idx]
def hf_bursts(x, z=6):
    from scipy.signal import butter,sosfilt
    sos=butter(4,5000,'hp',fs=SR,output='sos'); y=sosfilt(sos,x)
    f=int(0.005*SR); n=len(y)//f
    e=np.sqrt((y[:n*f].reshape(n,f)**2).mean(1))
    tot=np.sqrt((x[:n*f].reshape(n,f)**2).mean(1))+1e-6
    r=e/tot
    return [(i*f/SR,float(r[i])) for i in np.where(r>0.6)[0]]  # HF share high
def gaps(x, thr=1e-4, min_ms=15):
    act=np.where(np.abs(x)>0.01)[0]
    if len(act)==0: return []
    s,e=act[0],act[-1]
    quiet=(np.abs(x)<thr)
    out=[];i=s
    while i<e:
        if quiet[i]:
            j=i
            while j<e and quiet[j]: j+=1
            if (j-i)/SR*1000>=min_ms: out.append((i/SR,(j-i)/SR*1000))
            i=j
        else: i+=1
    return out
def lowgaps(x, ms=60, rel=0.02):
    # runs of 10 ms frame rms < rel*speech rms inside speech
    f=int(0.01*SR); n=len(x)//f
    r=np.sqrt((x[:n*f].reshape(n,f)**2).mean(1))
    ref=np.percentile(r[r>0.005],75) if (r>0.005).any() else 1
    q=r<rel*ref
    act=np.where(r>0.05*ref)[0]
    if len(act)==0: return []
    out=[];i=act[0]
    while i<act[-1]:
        if q[i]:
            j=i
            while j<act[-1] and q[j]: j+=1
            if (j-i)*10>=ms: out.append((i*f/SR,(j-i)*10.0))
            i=j
        else: i+=1
    return out
