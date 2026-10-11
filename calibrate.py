"""
calibrate.py - Measure your real error rates and pick thresholds from data.

1) Spoof detection (PAD). Record photos/frames with YOUR camera:
     data/pad/real/*.jpg    live people, varied lighting/angles
     data/pad/spoof/*.jpg   attacks: printed photo, phone screen, tablet, replay
   python calibrate.py pad --dir data/pad

2) Recognition. One folder per person (5+ varied images each, 2+ people):
     data/faces/alice/*.jpg
     data/faces/bob/*.jpg
   python calibrate.py recog --dir data/faces

Then copy the suggested values into Config in face_system.py:
  live_score_thresh  <- from the PAD report
  match_thresh       <- from the recognition report
"""
import argparse
import glob
import os
import random

import cv2
import numpy as np

from face_system import Config, FaceEngine, SpoofDetector

EXT = (".jpg", ".jpeg", ".png", ".bmp")


def images(folder):
    return sorted(p for p in glob.glob(os.path.join(folder, "*"))
                  if p.lower().endswith(EXT))


# ------------------------------- PAD -----------------------------------------
def pad_scores(engine, spoof, folder):
    scores, skipped = [], 0
    for p in images(folder):
        img = cv2.imread(p)
        f = engine.largest_face(img) if img is not None else None
        if f is None:
            skipped += 1
            continue
        scores.append(spoof.score(img, f.bbox))
    return np.array(scores), skipped


def pad_report(real, spoof):
    ts = np.linspace(0, 1, 1001)
    apcer = np.array([(spoof >= t).mean() for t in ts])   # spoof accepted
    bpcer = np.array([(real < t).mean() for t in ts])     # real rejected
    i = int(np.argmin(np.abs(apcer - bpcer)))
    print(f"\nEER ~ {100 * (apcer[i] + bpcer[i]) / 2:.2f}% at threshold {ts[i]:.3f}")
    print("\nTarget APCER   threshold   resulting BPCER")
    for target in (0.05, 0.01, 0.001):
        idx = np.where(apcer <= target)[0]
        if len(idx):
            j = idx[0]
            print(f"  {target * 100:5.1f}%      {ts[j]:.3f}       {bpcer[j] * 100:.2f}%")
        else:
            print(f"  {target * 100:5.1f}%      not reachable with this model/data")
    print("\nAPCER = attacks wrongly accepted, BPCER = real users wrongly rejected.")


# ------------------------------- Recognition ---------------------------------
def recog_report(engine, folder, max_imp=300000, seed=0):
    rng = random.Random(seed)
    embs = {}
    for person in sorted(os.listdir(folder)):
        d = os.path.join(folder, person)
        if not os.path.isdir(d):
            continue
        es = []
        for p in images(d):
            img = cv2.imread(p)
            f = engine.largest_face(img) if img is not None else None
            if f is not None:
                es.append(f.normed_embedding)
        if len(es) >= 2:
            embs[person] = np.stack(es)
    if len(embs) < 2:
        raise SystemExit("Need at least 2 people with 2+ usable images each.")

    gen = []
    for E in embs.values():
        S = E @ E.T
        gen.extend(S[np.triu_indices(len(E), 1)].tolist())
    imp = []
    people = list(embs)
    for i in range(len(people)):
        for j in range(i + 1, len(people)):
            imp.extend((embs[people[i]] @ embs[people[j]].T).ravel().tolist())
    if len(imp) > max_imp:
        imp = rng.sample(imp, max_imp)
    gen, imp = np.array(gen), np.array(imp)

    ts = np.linspace(-0.2, 1.0, 1201)
    far = np.array([(imp >= t).mean() for t in ts])    # impostor accepted
    frr = np.array([(gen < t).mean() for t in ts])     # genuine rejected
    i = int(np.argmin(np.abs(far - frr)))
    print(f"\nPeople: {len(embs)} | genuine pairs: {len(gen)} | impostor pairs: {len(imp)}")
    print(f"Genuine mean sim {gen.mean():.3f} | impostor mean sim {imp.mean():.3f}")
    print(f"EER ~ {100 * (far[i] + frr[i]) / 2:.2f}% at threshold {ts[i]:.3f}")
    print("\nTarget FAR   threshold   resulting FRR")
    for target in (0.01, 0.001, 0.0001):
        if len(imp) < 10 / target:
            print(f"  {target * 100:6.2f}%    (too few impostor pairs to trust)")
            continue
        idx = np.where(far <= target)[0]
        if len(idx):
            j = idx[0]
            print(f"  {target * 100:6.2f}%     {ts[j]:.3f}       {frr[j] * 100:.2f}%")
    print("\nFAR = strangers wrongly accepted, FRR = enrolled users wrongly rejected.")
    print("More people and images give more trustworthy numbers.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["pad", "recog"])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()
    cfg = Config(use_gpu=not args.cpu)
    engine = FaceEngine(cfg)

    if args.mode == "pad":
        spoof = SpoofDetector(cfg)
        real, sk_r = pad_scores(engine, spoof, os.path.join(args.dir, "real"))
        fake, sk_s = pad_scores(engine, spoof, os.path.join(args.dir, "spoof"))
        print(f"real images used: {len(real)} (no face found: {sk_r})")
        print(f"spoof images used: {len(fake)} (no face found: {sk_s})")
        if len(real) == 0 or len(fake) == 0:
            raise SystemExit("Need images in both real/ and spoof/.")
        pad_report(real, fake)
    else:
        recog_report(engine, args.dir)


if __name__ == "__main__":
    main()
