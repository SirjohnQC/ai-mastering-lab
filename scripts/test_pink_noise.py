"""Generate a safe deterministic pink-ish noise WAV and test frequency-selective processing.

Full pink PSD isn't essential here; this uses an FFT-domain 1/sqrt(f) spectrum.
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import soundfile as sf
from scipy.signal import welch
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
from mastering_lab.host import run_host
from mastering_lab.proq4 import build_changes

def make_noise(path: Path, seconds: int=4, sample_rate:int=48000):
    rng=np.random.default_rng(2026)
    n=seconds*sample_rate
    bins=np.fft.rfftfreq(n,1/sample_rate)
    spectrum=(rng.standard_normal(len(bins))+1j*rng.standard_normal(len(bins))) / np.sqrt(np.maximum(bins,20.))
    spectrum[0]=0
    signal=np.fft.irfft(spectrum,n=n)
    signal=signal/max(1e-12,np.max(np.abs(signal)))*.12
    sf.write(path,np.repeat(signal[:,None],2,axis=1),sample_rate,subtype='PCM_24')

def band_energy(signal,sr,low,high):
    f,psd=welch(signal,fs=sr,nperseg=8192)
    return float(np.sum(psd[(f>=low)&(f<=high)]))

def compare(original:Path,processed:Path):
    a,sr=sf.read(original,dtype='float64');b,sr2=sf.read(processed,dtype='float64')
    if sr!=sr2 or a.shape!=b.shape:raise ValueError('Audio shape/sample rate mismatch')
    # Remove global gain difference by comparing ratio at targeted vs reference bands.
    aa=a.mean(axis=1);bb=b.mean(axis=1)
    near=10*np.log10(max(band_energy(bb,sr,800,1250),1e-20)/max(band_energy(aa,sr,800,1250),1e-20))
    far=10*np.log10(max(band_energy(bb,sr,6000,9000),1e-20)/max(band_energy(aa,sr,6000,9000),1e-20))
    print(f'1 kHz band change: {near:+.2f} dB; high band change: {far:+.2f} dB')
    print(f'Frequency-specific effect (relative): {near-far:+.2f} dB')
    if near-far < 1.5:
        raise SystemExit('FAIL: did not detect expected selective 1 kHz boost')
    print('PASS: boosted energy around 1 kHz relative to high frequencies')

def main():
    plugin=Path(r'C:\Program Files\Common Files\VST3\FabFilter\FabFilter Pro-Q 4.vst3')
    host=root/'native/build/mastering-host_artefacts/Release/mastering-host.exe'
    source=root/'pink-test.wav'; output=root/'pink-eq.wav'
    make_noise(source)
    print('Created',source)
    ins=run_host(host,'inspect',plugin=plugin)
    changes=build_changes(ins,[{'center_hz':1000,'recommended_gain_db':3.0}],min_db=.01)
    result=run_host(host,'render',plugin=plugin,input_file=source,output_file=output,parameter_changes=changes)
    print('Rendered',output,'host status:',result.get('status'))
    compare(source,output)
if __name__=='__main__':main()
