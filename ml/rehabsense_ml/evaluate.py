"""Subject-independent evaluation, robustness and cost measurement.

Protocol (identical for every model so results are comparable):

  * GroupKFold by subject. Every test subject is unseen in training.
  * Anything fitted to data (feature scaling, network weights, early stopping)
    sees only the training fold; early stopping holds out whole subjects from
    the training fold, never test windows.
  * Metrics are pooled over all test folds: accuracy, macro F1 (the headline,
    because classes are imbalanced), per-class F1 and a confusion matrix.
  * Robustness: the trained fold model is re-scored on perturbed copies of its
    own test windows (transforms.PERTURBATIONS).
  * Cost: single-window CPU latency (features + model, median of 200), model
    size on disk, and peak Python memory during one inference.
"""

from __future__ import annotations

import io
import time
import tracemalloc

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold

from app.sensing import features as F
from rehabsense_ml.transforms import PERTURBATIONS
from rehabsense_ml.windows import WindowSet


def feature_matrix(ws: WindowSet, kind: str = "invariant", left=None, right=None,
                   g0_left=None, g0_right=None) -> np.ndarray:
    left = ws.left if left is None else left
    right = ws.right if right is None else right
    g0_left = ws.g0_left if g0_left is None else g0_left
    g0_right = ws.g0_right if g0_right is None else g0_right
    if kind == "invariant":
        if right is not None:
            return F.bilateral_features(left, right, ws.rate_hz, g0_left, g0_right)
        return F.side_features(left, ws.rate_hz, g0_left)
    if kind == "raw":
        parts = [F.raw_axis_features(left, ws.rate_hz)]
        if right is not None:
            parts.append(F.raw_axis_features(right, ws.rate_hz))
        return np.concatenate(parts, axis=1)
    raise ValueError(kind)


def _summary(y_true, y_pred, classes) -> dict:
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, average="macro", labels=classes,
                                         zero_division=0)), 4),
        "per_class_f1": {c: round(float(v), 4) for c, v in zip(
            classes, f1_score(y_true, y_pred, average=None, labels=classes, zero_division=0))},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=classes).tolist(),
        "classes": list(classes),
    }


def folds(ws: WindowSet, n_splits: int):
    return list(GroupKFold(n_splits=n_splits).split(np.zeros(len(ws)), ws.y, ws.groups))


def _perturbed(ws: WindowSet, name: str, rng):
    """Perturbed (left, right, g0_left, g0_right) copies of a window set."""
    fn = PERTURBATIONS[name]
    left, gl = fn(ws.left, ws.g0_left, rng)
    if ws.right is None:
        return left, None, gl, None
    right, gr = fn(ws.right, ws.g0_right, rng)
    return left, right, gl, gr


def _augmented_features(ws: WindowSet, kind: str, rng) -> np.ndarray:
    from rehabsense_ml.transforms import augment_device_like

    left, gl = augment_device_like(ws.left, ws.g0_left, rng)
    right, gr = (None, None) if ws.right is None else augment_device_like(ws.right, ws.g0_right, rng)
    return feature_matrix(ws, kind, left, right, gl, gr)


def evaluate_feature_model(ws: WindowSet, make_model, kind: str, n_splits: int = 4,
                           perturb: tuple = tuple(PERTURBATIONS), seed: int = 0,
                           augment: bool = False) -> dict:
    classes = sorted(set(ws.y))
    X = feature_matrix(ws, kind)
    preds = np.empty(len(ws), dtype=object)
    robust = {p: np.empty(len(ws), dtype=object) for p in perturb}
    fold_scores = []
    t_train = 0.0
    first_model = None
    rng = np.random.default_rng(seed)
    for k, (tr, te) in enumerate(folds(ws, n_splits)):
        model = make_model()
        t0 = time.perf_counter()
        if augment:
            Xa = _augmented_features(ws.subset(tr), kind, rng)
            model.fit(np.concatenate([X[tr], Xa]), np.concatenate([ws.y[tr], ws.y[tr]]))
        else:
            model.fit(X[tr], ws.y[tr])
        t_train += time.perf_counter() - t0
        preds[te] = model.predict(X[te])
        fold_scores.append(round(float(f1_score(ws.y[te], preds[te], average="macro",
                                                zero_division=0)), 4))
        sub = ws.subset(te)
        for p in perturb:
            l, r, gl, gr = _perturbed(sub, p, rng)
            robust[p][te] = model.predict(feature_matrix(sub, kind, l, r, gl, gr))
        if first_model is None:
            first_model = model
    out = _summary(ws.y, preds, classes)
    out["fold_macro_f1"] = fold_scores
    out["robustness_macro_f1"] = {
        p: round(float(f1_score(ws.y, robust[p], average="macro", zero_division=0)), 4)
        for p in perturb
    }
    out["train_seconds_total"] = round(t_train, 1)
    out.update(_cost_sklearn(first_model, ws, kind))
    return out


def _cost_sklearn(model, ws: WindowSet, kind: str) -> dict:
    one = ws.subset(np.array([0]))
    model.n_jobs = 1 if hasattr(model, "n_jobs") else None

    def infer():
        return model.predict_proba(feature_matrix(one, kind))

    infer()
    times = []
    for _ in range(200):
        t0 = time.perf_counter()
        infer()
        times.append((time.perf_counter() - t0) * 1000)
    tracemalloc.start()
    infer()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    buf = io.BytesIO()
    joblib.dump(model, buf, compress=3)
    return {
        "latency_ms_p50": round(float(np.median(times)), 3),
        "latency_ms_p95": round(float(np.percentile(times, 95)), 3),
        "model_bytes": buf.getbuffer().nbytes,
        "inference_peak_python_mem_bytes": int(peak),
    }


# ---------------------------------------------------------------------- #
# deep models
# ---------------------------------------------------------------------- #

def _channels(imu: np.ndarray, g0: np.ndarray) -> np.ndarray:
    """(W, n, 6) raw + neutral -> (W, 9, n): 6 invariant channels plus tilt
    from neutral, acceleration along neutral vertical, rotation about it."""
    inv = F.invariant_channels(imu)
    acc, gyr = imu[..., 0:3], imu[..., 3:6]
    unit = acc / np.maximum(np.linalg.norm(acc, axis=-1, keepdims=True), 1e-9)
    tilt = np.degrees(np.arccos(np.clip(np.einsum("wnk,wk->wn", unit, g0), -1, 1)))
    along = np.einsum("wnk,wk->wn", acc, g0)
    about = np.einsum("wnk,wk->wn", gyr, g0)
    x = np.concatenate([inv, tilt[..., None], along[..., None], about[..., None]], axis=-1)
    return np.transpose(x, (0, 2, 1)).astype(np.float32)


def evaluate_deep(ws: WindowSet, temporal: str, n_splits: int = 4, epochs: int = 15,
                  perturb: tuple = tuple(PERTURBATIONS), seed: int = 0,
                  init_encoder: dict | None = None, batch: int = 256) -> dict:
    import torch

    from rehabsense_ml.models.deep import FusionNet, n_params

    torch.manual_seed(seed)
    torch.set_num_threads(4)
    classes = sorted(set(ws.y))
    cidx = {c: i for i, c in enumerate(classes)}
    y = np.array([cidx[c] for c in ws.y])
    bilateral = ws.right is not None
    XL = _channels(ws.left, ws.g0_left)
    XR = _channels(ws.right, ws.g0_right) if bilateral else None
    preds = np.empty(len(ws), dtype=object)
    robust = {p: np.empty(len(ws), dtype=object) for p in perturb}
    fold_scores = []
    rng = np.random.default_rng(seed)
    t_train = 0.0
    model = None
    stats = None
    for k, (tr, te) in enumerate(folds(ws, n_splits)):
        # Early-stopping subjects come from the training fold only.
        tr_subjects = np.unique(ws.groups[tr])
        val_subj = tr_subjects[k % len(tr_subjects)]
        val = tr[ws.groups[tr] == val_subj]
        fit = tr[ws.groups[tr] != val_subj]
        pool = np.concatenate([XL[fit]] + ([XR[fit]] if bilateral else []))
        mu = pool.mean(axis=(0, 2), keepdims=True)
        sd = pool.std(axis=(0, 2), keepdims=True) + 1e-6
        stats = (mu, sd)

        def prep(a):
            return torch.from_numpy((a - mu) / sd)

        model = FusionNet(len(classes), temporal=temporal, bilateral=bilateral)
        if init_encoder is not None:
            model.encoder.load_state_dict(init_encoder)
        opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-3)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
        counts = np.bincount(y[fit], minlength=len(classes)).astype(np.float32)
        loss_fn = torch.nn.CrossEntropyLoss(
            weight=torch.from_numpy(counts.sum() / np.maximum(counts, 1) / len(classes)))
        best, best_state, patience = -1.0, None, 0
        t0 = time.perf_counter()
        for ep in range(epochs):
            model.train()
            order = rng.permutation(fit)
            for i in range(0, len(order), batch):
                b = order[i:i + batch]
                l, r = XL[b], (XR[b] if bilateral else None)
                if bilateral and rng.random() < 0.5:
                    l, r = r, l   # side swap: activity does not depend on which leg
                opt.zero_grad()
                out = model(prep(l), prep(r) if bilateral else None)
                loss = loss_fn(out, torch.from_numpy(y[b]))
                loss.backward()
                opt.step()
            sched.step()
            score = _deep_f1(model, prep, XL, XR, y, val, bilateral)
            if score > best:
                best, patience = score, 0
                best_state = {k2: v.clone() for k2, v in model.state_dict().items()}
            else:
                patience += 1
                if patience >= 4:
                    break
        t_train += time.perf_counter() - t0
        model.load_state_dict(best_state)
        model.eval()
        p = _deep_predict(model, prep, XL[te], XR[te] if bilateral else None)
        preds[te] = np.array(classes)[p]
        fold_scores.append(round(float(f1_score(ws.y[te], preds[te], average="macro",
                                                zero_division=0)), 4))
        sub = ws.subset(te)
        for name in perturb:
            l, r, gl, gr = _perturbed(sub, name, rng)
            pr = _deep_predict(model, prep, _channels(l, gl),
                               _channels(r, gr) if bilateral else None)
            robust[name][te] = np.array(classes)[pr]
    out = _summary(ws.y, preds, classes)
    out["fold_macro_f1"] = fold_scores
    out["robustness_macro_f1"] = {
        p: round(float(f1_score(ws.y, robust[p], average="macro", zero_division=0)), 4)
        for p in perturb
    }
    out["train_seconds_total"] = round(t_train, 1)
    out.update(_cost_torch(model, ws, stats, bilateral))
    out["parameters"] = n_params(model)
    return out


def _deep_predict(model, prep, XL, XR, batch=2048):
    import torch

    out = []
    with torch.no_grad():
        for i in range(0, len(XL), batch):
            logits = model(prep(XL[i:i + batch]), prep(XR[i:i + batch]) if XR is not None else None)
            out.append(logits.argmax(1).numpy())
    return np.concatenate(out)


def _deep_f1(model, prep, XL, XR, y, idx, bilateral):
    model.eval()
    p = _deep_predict(model, prep, XL[idx], XR[idx] if bilateral else None)
    model.train()
    return f1_score(y[idx], p, average="macro", zero_division=0)


def _cost_torch(model, ws, stats, bilateral) -> dict:
    import torch

    mu, sd = stats
    one = ws.subset(np.array([0]))
    torch.set_num_threads(1)

    def infer():
        l = torch.from_numpy((_channels(one.left, one.g0_left) - mu) / sd)
        r = torch.from_numpy((_channels(one.right, one.g0_right) - mu) / sd) if bilateral else None
        with torch.no_grad():
            return torch.softmax(model(l, r), 1)

    infer()
    times = []
    for _ in range(200):
        t0 = time.perf_counter()
        infer()
        times.append((time.perf_counter() - t0) * 1000)
    torch.set_num_threads(4)
    buf = io.BytesIO()
    torch.save(model.state_dict(), buf)
    return {
        "latency_ms_p50": round(float(np.median(times)), 3),
        "latency_ms_p95": round(float(np.percentile(times, 95)), 3),
        "model_bytes": buf.getbuffer().nbytes,
    }


def pretrain_encoder(ws_single: WindowSet, temporal: str, epochs: int = 15, seed: int = 0) -> dict:
    """Train a single-side model on all given windows; return encoder weights.

    Used to pretrain on PAMAP2 (ankle) before training on Daily & Sports. The
    PAMAP2 subjects never appear in the Daily & Sports evaluation folds.
    """
    import torch

    from rehabsense_ml.models.deep import FusionNet

    torch.manual_seed(seed)
    classes = sorted(set(ws_single.y))
    cidx = {c: i for i, c in enumerate(classes)}
    y = np.array([cidx[c] for c in ws_single.y])
    X = _channels(ws_single.left, ws_single.g0_left)
    mu = X.mean(axis=(0, 2), keepdims=True)
    sd = X.std(axis=(0, 2), keepdims=True) + 1e-6
    Xt = torch.from_numpy((X - mu) / sd)
    model = FusionNet(len(classes), temporal=temporal, bilateral=False)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-3)
    rng = np.random.default_rng(seed)
    loss_fn = torch.nn.CrossEntropyLoss()
    for _ in range(epochs):
        model.train()
        order = rng.permutation(len(y))
        for i in range(0, len(order), 256):
            b = order[i:i + 256]
            opt.zero_grad()
            loss = loss_fn(model(Xt[b]), torch.from_numpy(y[b]))
            loss.backward()
            opt.step()
    return {k: v.clone() for k, v in model.encoder.state_dict().items()}
