from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import Iterable, List, Dict, Tuple, Any
from collections import Counter, defaultdict
import math

# Optional: pip install datasketch networkx
try:
    from datasketch import MinHash, MinHashLSH
    import networkx as nx
    HAS_DATASKETCH = True
except ImportError:
    HAS_DATASKETCH = False
    print("Warning: datasketch and networkx not available. Install with: pip install datasketch networkx")

# =========================
# 1) Canonicalización
# =========================


def _norm_text_bucket(text: str | None) -> Tuple[str, str]:
    if not text:
        return ("len_0", "pat_none")
    t = text.strip().lower()
    # bucket por longitud
    L = len(t)
    if L <= 5:
        bl = "len_1_5"
    elif L <= 20:
        bl = "len_6_20"
    elif L <= 80:
        bl = "len_21_80"
    else:
        bl = "len_81p"
    # patrón (quitar dígitos y espacios)
    import re
    base = re.sub(r"\d+", "<num>", t)
    base = re.sub(r"\s+", " ", base).strip()
    ph = hashlib.sha1(base.encode()).hexdigest()[:8]
    return (bl, f"pat_{ph}")


def _norm_selector(selector) -> str:
    # Usa tus tipos: ATTRIBUTE_VALUE_SELECTOR, TAG_CONTAINS_SELECTOR, XPATH_SELECTOR
    if selector is None:
        return "sel:none"
    try:
        # preferimos atributos estables
        attr = getattr(selector, "attribute", None)
        val = getattr(selector, "value", None)
        t = getattr(selector, "type", None) or ""
        if attr in {"data-testid", "aria-label", "name", "role", "placeholder", "title"} and val:
            base = f"{attr}={val}".lower().strip()
            return f"sel:{attr}:{hashlib.md5(base.encode()).hexdigest()[:8]}"
        # texto aproximado
        if t == "tagContainsSelector" and val:
            return f"sel:text:{hashlib.md5(val.lower().encode()).hexdigest()[:8]}"
        # xpath/cualquier otro → hash corto
        rep = f"{t}|{attr}|{val}"
        return f"sel:hash:{hashlib.md5(rep.encode()).hexdigest()[:8]}"
    except Exception:
        return "sel:error"


def _norm_url(url: str | None) -> str:
    if not url:
        return "url:none"
    # host + 2 primeros segmentos de path
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        host = (p.netloc or "").lower()
        segs = [s for s in (p.path or "").split("/") if s][:2]
        base = host + "/" + "/".join(segs)
        return "url:" + hashlib.md5(base.encode()).hexdigest()[:8]
    except Exception:
        return "url:err"


def canonical_token(action) -> str:
    """
    Produce un token estable por acción:
    - tipo de acción
    - selector semántico canonicalizado
    - buckets de payload relevantes
    - url (si la acción la tiene o aportas el contexto fuera)
    """
    a_type = (getattr(action, "type", "") or "").lower()

    # selector
    sel = getattr(action, "selector", None)
    sel_tok = _norm_selector(sel)

    # texto / value
    text = getattr(action, "text", None)
    value = getattr(action, "value", None)
    t_bucket, t_pat = _norm_text_bucket(text if text is not None else (value if isinstance(value, str) else None))

    # navegación
    url = getattr(action, "url", None)
    url_tok = _norm_url(url)

    # scroll / direcciones
    dirs = []
    for d in ("up","down","left","right"):
        if getattr(action, d, False):
            dirs.append(d)
    dir_tok = "dir:" + ("-".join(sorted(dirs)) if dirs else "none")

    # clicks por coordenadas → binariza (ignoramos XY)
    xy_tok = "xy:" + ("coord" if (getattr(action, "x", None) is not None and getattr(action, "y", None) is not None) else "sel")

    # especiales
    extra = []
    if a_type == "waitaction":
        # bucketizar tiempos
        ts = getattr(action, "time_seconds", None)
        if ts is None:
            wbin = "w:sel"
        elif ts <= 0.1:
            wbin = "w:0_100ms"
        elif ts <= 0.3:
            wbin = "w:100_300ms"
        elif ts <= 0.8:
            wbin = "w:300_800ms"
        elif ts <= 2.0:
            wbin = "w:0.8_2s"
        else:
            wbin = "w:2s_plus"
        extra.append(wbin)
    if a_type == "selectaction":
        # value puede ser índice/texto; lo bucketizamos por hash corto
        if isinstance(value, str) and value:
            extra.append("selv:" + hashlib.sha1(value.lower().strip().encode()).hexdigest()[:6])

    base = "|".join([a_type, sel_tok, t_bucket, t_pat, url_tok, dir_tok, xy_tok] + extra)
    # token final corto (pero estable)
    return hashlib.sha1(base.encode()).hexdigest()[:12]


def canonical_sequence(solution) -> List[str]:
    return [canonical_token(a) for a in solution.actions]

# =========================
# 2) Huellas multi-vista
# =========================


def shingles(tokens: List[str], k: int = 4) -> List[str]:
    if len(tokens) < k:
        return ["|".join(tokens)]
    return ["|".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)]


def minhash_signature(shingle_set: Iterable[str], num_perm: int = 128):
    if not HAS_DATASKETCH:
        # Fallback simple si no hay datasketch
        return None
    m = MinHash(num_perm=num_perm)
    for s in set(shingle_set):
        m.update(s.encode())
    return m


def seq_hash_embed(tokens: List[str], dim: int = 256) -> List[float]:
    # Embedding ligero por hashing (sin entrenar): estable y barato.
    vec = [0.0] * dim
    for i, tk in enumerate(tokens):
        h = int(hashlib.blake2b(tk.encode(), digest_size=8).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 1.0
    # normaliza L2
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x,y in zip(a,b))


def weighted_edit_similarity(a: List[str], b: List[str]) -> float:
    # distancia de edición con coste bajo cuando tokens iguales; alto si distintos.
    # Implementación simple O(n*m) suficiente para candidatos.
    n,m = len(a), len(b)
    if n == 0 and m == 0:
        return 1.0
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1,n + 1):
        for j in range(1,m + 1):
            cost_sub = 0 if a[i - 1] == b[j - 1] else 1.2  # sustituir distinto cuesta más
            dp[i][j] = min(
                dp[i - 1][j] + 0.8,         # borrado
                dp[i][j - 1] + 0.8,         # inserción
                dp[i - 1][j - 1] + cost_sub   # sustitución
            )
    dist = dp[n][m]
    max_len = max(n,m) or 1
    # sim en [0,1]
    return max(0.0, 1.0 - dist / (1.2 * max_len))


def behavior_stats(tokens: List[str]) -> List[float]:
    # Contamos "familias" de tokens decodificando prefijo de tipo (guardado en el token original no está;
    # truco: volvemos a obtener familias aproximando por hash buckets del token)
    # Alternativa: extraer de acciones reales antes de canonizar; si no, usamos n-gram counts.
    c = Counter(tokens)
    total = sum(c.values()) or 1
    # Top 32 tokens más comunes → vector fijo 32 (orden por frecuencia global)
    top = [cnt / total for _, cnt in c.most_common(32)]
    # completa a 32
    return top + [0.0] * (32 - len(top))


@dataclass
class SolutionFingerprint:
    task_id: str
    tokens: List[str]
    shingles: List[str]
    minhash: Any  # MinHash or None
    embed: List[float]
    stats: List[float]


def fingerprint_solution(sol) -> SolutionFingerprint:
    toks = canonical_sequence(sol)
    sh = shingles(toks, k=4)
    mh = minhash_signature(sh, num_perm=128)
    emb = seq_hash_embed(toks, dim=256)
    st = behavior_stats(toks)
    return SolutionFingerprint(sol.task_id, toks, sh, mh, emb, st)

# =========================
# 3) Similitud solución-solución y agregación por miner
# =========================


def pair_similarity(fpA: SolutionFingerprint, fpB: SolutionFingerprint) -> float:
    # Jaccard estimado con MinHash (si disponible)
    if HAS_DATASKETCH and fpA.minhash is not None and fpB.minhash is not None:
        jac = fpA.minhash.jaccard(fpB.minhash)
    else:
        # Fallback: Jaccard simple sobre shingles
        set_a, set_b = set(fpA.shingles), set(fpB.shingles)
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        jac = intersection / union if union > 0 else 0.0

    # Cosine embeddings
    cos = cosine(fpA.embed, fpB.embed)
    # Edit distance ponderada
    edit = weighted_edit_similarity(fpA.tokens, fpB.tokens)
    # Stats cosine
    # (normalizadas ya aproximadamente)
    st = cosine(fpA.stats, fpB.stats)
    # mezcla (pesos calibrados)
    return 0.30 * jac + 0.35 * cos + 0.25 * edit + 0.10 * st


def aggregate_by_miner(similarities_same_task: List[float]) -> float:
    # mediana robusta
    if not similarities_same_task:
        return 0.0
    sims = sorted(similarities_same_task)
    mid = len(sims) // 2
    return (sims[mid] if len(sims) % 2 else 0.5 * (sims[mid - 1] + sims[mid]))

# =========================
# 4) LSH para candidatos & cluster
# =========================


class CandidateIndex:
    def __init__(self, threshold=0.6, num_perm=128, bands=32, rows=4):
        # threshold aprox; bands*rows debe igualar num_perm
        if HAS_DATASKETCH:
            self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm, params=(bands, rows))
        else:
            self.lsh = None
        self._store: Dict[str, SolutionFingerprint] = {}

    def add(self, key: str, fp: SolutionFingerprint):
        if self.lsh is not None and fp.minhash is not None:
            self.lsh.insert(key, fp.minhash)
        self._store[key] = fp

    def query_candidates(self, fp: SolutionFingerprint) -> List[Tuple[str, SolutionFingerprint]]:
        if self.lsh is not None and fp.minhash is not None:
            keys = self.lsh.query(fp.minhash)
            return [(k, self._store[k]) for k in keys]
        else:
            # Fallback: return all stored fingerprints
            return list(self._store.items())


def cluster_miners(miner_ids: List[str], S: Dict[Tuple[str,str], float], tau: float = 0.85):
    if not HAS_DATASKETCH:
        # Fallback simple: agrupa por similitud directa
        clusters = []
        used = set()
        for m in miner_ids:
            if m in used:
                continue
            cluster = {m}
            used.add(m)
            for other_m in miner_ids:
                if other_m in used:
                    continue
                pair = tuple(sorted((m, other_m)))
                if pair in S and S[pair] >= tau:
                    cluster.add(other_m)
                    used.add(other_m)
            clusters.append(cluster)
        return clusters

    G = nx.Graph()
    for m in miner_ids:
        G.add_node(m)
    for (i,j), s in S.items():
        if s >= tau:
            G.add_edge(i, j, weight=s)
    comps = list(nx.connected_components(G))
    return comps

# =========================
# 5) Entry point principal
# =========================


def compare_solutions(solutions: List[Any], min_shared_tasks: int = 6, tau: float = 0.85) -> Dict[str, List[str]]:
    """
    Compara soluciones y devuelve clusters de miners similares.

    Args:
        solutions: Lista de objetos con .miner_id, .task_id, .actions
        min_shared_tasks: Mínimo número de tareas compartidas para considerar similitud
        tau: Umbral de similitud para considerar dos miners como clones

    Returns:
        Dict con miner_id -> lista de miners en el mismo cluster
    """
    # Crear fingerprints por solución
    fps_by_miner_task: Dict[Tuple[str,str], SolutionFingerprint] = {}
    index = CandidateIndex(threshold=0.60, num_perm=128, bands=32, rows=4)

    for sol in solutions:
        fp = fingerprint_solution(sol)
        key = f"{sol.miner_id}|{sol.task_id}"
        fps_by_miner_task[(sol.miner_id, sol.task_id)] = fp
        index.add(key, fp)

    # Comparar solo pares en la misma tarea
    pair_sims_agg: Dict[Tuple[str,str], List[float]] = defaultdict(list)

    # Para cada tarea, saca los miners que la resolvieron
    tasks = {}
    for (miner, task), fp in fps_by_miner_task.items():
        tasks.setdefault(task, []).append((miner, fp))

    for task_id, lst in tasks.items():
        # Comparar todos los pares en la misma tarea
        for i, (mi, fpi) in enumerate(lst):
            for mj, fpj in lst[i + 1:]:
                s = pair_similarity(fpi, fpj)
                key = tuple(sorted((mi, mj)))
                pair_sims_agg[key].append(s)

    # Agregar por pareja de miners y decidir clones
    final_S: Dict[Tuple[str,str], float] = {}
    for pair, sims in pair_sims_agg.items():
        if len(sims) >= min_shared_tasks:
            final_S[pair] = aggregate_by_miner(sims)

    # Marca "misma entidad" si S >= tau
    miners = sorted({m for m,_ in fps_by_miner_task})
    clusters = cluster_miners(miners, final_S, tau=tau)

    # Convertir a formato de salida
    result = {}
    for cluster in clusters:
        cluster_list = list(cluster)
        for miner in cluster_list:
            result[miner] = cluster_list

    return result


def get_similarity_score(sol1: Any, sol2: Any) -> float:
    """
    Entry point simple para comparar dos soluciones directamente.

    Args:
        sol1, sol2: Objetos con .actions (lista de acciones)

    Returns:
        Score de similitud entre 0.0 y 1.0
    """
    # Ensure we can pass a task_id for fingerprinting stability; use a default if missing
    if not hasattr(sol1, "task_id"):
        setattr(sol1, "task_id", "_task")
    if not hasattr(sol2, "task_id"):
        setattr(sol2, "task_id", "_task")
    fp1 = fingerprint_solution(sol1)
    fp2 = fingerprint_solution(sol2)
    return pair_similarity(fp1, fp2)

