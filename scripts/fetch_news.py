#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telecom Radar - coletor e curador de noticias de telecomunicacoes.

Le uma lista curada de feeds RSS/Atom, pontua relevancia (sinal vs ruido),
classifica cada item por TEMA (moveis / fibra / antenas / iot / satelite /
radar-militar / radiocom / tv / geral), marca se eh PESQUISA (arXiv, papers)
e detecta PAISES citados (russia, israel, india, japao, coreia, china).
Deduplica e grava data/news.json para o frontend estatico consumir.

Um item pode ter varios temas ao mesmo tempo (multi-rotulo). A pesquisa eh um
sinalizador a parte (nao eh tema), entao da pra liga-la ou desliga-la sem mexer
nos temas. Os paises tambem sao a parte: servem de "foco" opcional.

Roda no GitHub Actions (cron). Sem dependencias alem de feedparser.
"""

import json
import re
import sys
import time
import html
import hashlib
import datetime as dt
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import feedparser

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "news.json"

# -------------------------------------------------------------------
# FONTES
# region: "ground" (terrestre) ou "satellite" (forca o tema satelite)
# kind:   "research" marca a fonte como pesquisa (todos os itens viram pesquisa)
# weight: multiplicador de relevancia da fonte (padroes e pesquisa valem mais)
# strict: se True, so entra item que cruzar o limiar de relevancia
#         (feeds amplos) - feeds tecnicos/labs entram sempre
# cap:    maximo de itens por fonte nesta rodada
#
# Feed que sair do ar e ignorado sem quebrar a coleta. Veja o campo "sources"
# no news.json para o status de cada um na ultima rodada e ajuste a vontade.
# -------------------------------------------------------------------
SOURCES = [
    # --- Imprensa especializada / industria (terrestre) ---
    {"name": "Light Reading",       "url": "https://www.lightreading.com/rss.xml",                     "region": "ground", "weight": 1.4, "strict": False, "cap": 12},
    {"name": "Fierce Network",      "url": "https://www.fierce-network.com/rss/xml",                   "region": "ground", "weight": 1.3, "strict": False, "cap": 12},
    {"name": "Telecoms.com",        "url": "https://www.telecoms.com/feed/",                           "region": "ground", "weight": 1.3, "strict": False, "cap": 12},
    {"name": "RCR Wireless",        "url": "https://feeds.feedburner.com/rcrwireless",                 "region": "ground", "weight": 1.3, "strict": False, "cap": 12},
    {"name": "Mobile World Live",   "url": "https://www.mobileworldlive.com/feed/",                    "region": "ground", "weight": 1.3, "strict": False, "cap": 10},
    {"name": "TelecomTV",           "url": "https://www.telecomtv.com/rss/",                           "region": "ground", "weight": 1.2, "strict": False, "cap": 10},
    {"name": "Telecompetitor",      "url": "https://www.telecompetitor.com/feed/",                     "region": "ground", "weight": 1.1, "strict": True,  "cap": 8},
    {"name": "The Fast Mode",       "url": "https://www.thefastmode.com/feed",                         "region": "ground", "weight": 1.1, "strict": True,  "cap": 8},
    {"name": "Total Telecom",       "url": "https://www.totaltele.com/feed/",                          "region": "ground", "weight": 1.1, "strict": True,  "cap": 8},
    {"name": "TeckNexus",           "url": "https://tecknexus.com/feed",                               "region": "ground", "weight": 1.0, "strict": True,  "cap": 8},
    {"name": "Telecoms Tech News",  "url": "https://www.telecomstechnews.com/feed/",                   "region": "ground", "weight": 1.0, "strict": True,  "cap": 8},
    {"name": "CircleID (Telecom)",  "url": "https://circleid.com/rss/topics/telecom",                  "region": "ground", "weight": 1.0, "strict": True,  "cap": 6},
    {"name": "DataCenterDynamics",  "url": "https://www.datacenterdynamics.com/en/rss/",               "region": "ground", "weight": 0.95, "strict": True, "cap": 6},
    {"name": "Capacity Media",      "url": "https://www.capacitymedia.com/feed",                       "region": "ground", "weight": 1.0, "strict": True,  "cap": 6},
    {"name": "Telecom Lead",        "url": "https://www.telecomlead.com/feed",                         "region": "ground", "weight": 0.95, "strict": True, "cap": 8},

    # --- Tecnologia / engenharia (terrestre) ---
    {"name": "3G4G Blog",           "url": "https://feeds.feedburner.com/3gAnd4g",                     "region": "ground", "weight": 1.4, "strict": False, "cap": 8},
    {"name": "IEEE Spectrum (Telecom)", "url": "https://spectrum.ieee.org/feeds/topic/telecommunications.rss", "region": "ground", "weight": 1.2, "strict": False, "cap": 8},
    {"name": "Ericsson Blog",       "url": "https://www.ericsson.com/en/blog/rss",                     "region": "ground", "weight": 1.2, "strict": False, "cap": 6},
    {"name": "Nokia Blog",          "url": "https://www.nokia.com/blog/feed/",                         "region": "ground", "weight": 1.2, "strict": False, "cap": 6},

    # --- Padroes e organizacoes (terrestre, alto peso) ---
    {"name": "IEEE ComSoc Tech Blog", "url": "https://techblog.comsoc.org/feed/",                      "region": "ground", "weight": 1.4, "strict": False, "cap": 8},
    {"name": "One6G",               "url": "https://one6g.org/feed/",                                  "region": "ground", "weight": 1.2, "strict": False, "cap": 5},
    {"name": "6G-IA",               "url": "https://6g-ia.eu/feed/",                                   "region": "ground", "weight": 1.2, "strict": False, "cap": 5},
    {"name": "6GWorld",             "url": "https://www.6gworld.com/feed/",                            "region": "ground", "weight": 1.1, "strict": True,  "cap": 6},
    {"name": "3GPP News",           "url": "https://www.3gpp.org/news-events?format=feed&type=rss",    "region": "ground", "weight": 1.4, "strict": False, "cap": 6},
    {"name": "ETSI News",           "url": "https://www.etsi.org/index.php?format=feed&type=rss",      "region": "ground", "weight": 1.2, "strict": True,  "cap": 5},

    # --- Pesquisa primaria (arXiv -> kind research, strict + cap baixo) ---
    {"name": "arXiv eess.SP",       "url": "https://rss.arxiv.org/rss/eess.SP",   "region": "ground", "kind": "research", "weight": 1.3, "strict": True, "cap": 8},
    {"name": "arXiv cs.NI",         "url": "https://rss.arxiv.org/rss/cs.NI",     "region": "ground", "kind": "research", "weight": 1.3, "strict": True, "cap": 8},
    {"name": "arXiv cs.IT",         "url": "https://rss.arxiv.org/rss/cs.IT",     "region": "ground", "kind": "research", "weight": 1.2, "strict": True, "cap": 8},
    {"name": "arXiv eess.SY",       "url": "https://rss.arxiv.org/rss/eess.SY",   "region": "ground", "kind": "research", "weight": 1.0, "strict": True, "cap": 5},

    # --- Regulatorio / espectro (terrestre) ---
    {"name": "FCC Headlines",       "url": "https://www.fcc.gov/news-events/headlines/rss",            "region": "ground", "weight": 0.95, "strict": True, "cap": 6},

    # --- Comunicacao via satelite (forca o tema satelite) ---
    {"name": "SpaceNews",           "url": "https://spacenews.com/feed/",                              "region": "satellite", "weight": 1.3, "strict": True,  "cap": 10},
    {"name": "Via Satellite",       "url": "https://www.satellitetoday.com/feed/",                     "region": "satellite", "weight": 1.4, "strict": False, "cap": 10},
    {"name": "Advanced Television",  "url": "https://advanced-television.com/feed/",                    "region": "satellite", "weight": 1.0, "strict": True,  "cap": 8},
    {"name": "SatNews",             "url": "https://news.satnews.com/feed/",                           "region": "satellite", "weight": 1.0, "strict": True,  "cap": 8},
    {"name": "European Spaceflight", "url": "https://europeanspaceflight.com/feed/",                   "region": "satellite", "weight": 0.95, "strict": True, "cap": 6},
]

# -------------------------------------------------------------------
# LEXICO POR TEMA (multi-rotulo)
# Um item recebe um tema se cruzar >= 1 termo da lista daquele tema.
# Sobreposicao eh esperada e ok: um paper de MIMO vira [antenas, moveis].
# O tema "geral" nao tem lista: eh o balde de quem nao cruzou nenhum outro.
# Edite a vontade - adicionar termo aqui ja muda a classificacao na proxima coleta.
# -------------------------------------------------------------------
THEME_LEXICON = {
    "moveis": [
        "5g", "6g", "4g", "lte", "5g-advanced", "5g advanced", "5g-a",
        "standalone", "volte", "vonr", "vo5g", "open ran", "o-ran", "oran",
        "vran", "cloud ran", "c-ran", "radio access", "gnb", "enb",
        "base station", "small cell", "macro cell", "network slicing",
        "private 5g", "private network", "private cellular", "cbrs",
        "fwa", "fixed wireless", "5gc", "5g core", "epc", "mobile network",
        "mobile operator", "mno", "cellular", "handset", "subscriber",
        "roaming", "carrier aggregation", "redcap", "mvno", "mid-band",
        "sub-6", "mmwave", "millimeter wave", "massive mimo", "mimo",
    ],
    "fibra": [
        "fiber", "fibre", "ftth", "fttp", "fttx", "gpon", "xgs-pon", "xgspon",
        "ng-pon", "10g-pon", "docsis", "broadband", "fixed broadband",
        "gigabit", "fiber-to-the", "fttc", "fttn", "optical network",
        "optical fiber", "optical fibre", "dwdm", "cwdm", "roadm",
        "coherent optics", "subsea cable", "submarine cable", "undersea cable",
        "optical transport", "otn", "pon ",
    ],
    "antenas": [
        "antenna", "antennas", "massive mimo", "mimo", "beamforming",
        "beamformer", "phased array", "phased-array", "array antenna",
        "antenna array", "aperture", "radome", "feedhorn", "rf front-end",
        "rf frontend", "front-end module", "patch antenna", "dipole", "yagi",
        "reflectarray", "metasurface", "metamaterial", "ris",
        "reconfigurable intelligent surface", "irs", "radiation pattern",
        "smart antenna", "beam steering", "beam-steering",
    ],
    "iot": [
        "iot", "internet of things", "m2m", "nb-iot", "lte-m", "cat-m",
        "lpwan", "lora", "lorawan", "sigfox", "zigbee", "z-wave",
        "matter protocol", "thread protocol", "mqtt", "coap", "sensor network",
        "industrial iot", "iiot", "smart meter", "smart metering",
        "smart city", "smart cities", "asset tracking", "wearable",
        "connected device", "massive machine", "mmtc", "ambient iot",
        "ambient backscatter",
    ],
    "satelite": [
        "satellite", "satellites", "satcom", "sat-com", "ntn",
        "non-terrestrial", "non terrestrial", "constellation",
        "megaconstellation", "mega-constellation", "starlink", "oneweb",
        "kuiper", "ses ", "intelsat", "eutelsat", "viasat", "inmarsat",
        "iridium", "globalstar", "telesat", "lynk", "ast spacemobile",
        "ast space", "omnispace", "skylo", "oq technology", "direct-to-cell",
        "direct to cell", "satellite-to-cell", "sat-to-cell",
        "supplemental coverage from space", "vsat", "ground station",
        "earth station", "uplink", "downlink", "ka-band", "ku-band",
        "transponder", "geostationary", "geosynchronous", "low earth orbit",
        "leo satellite", "geo satellite", "meo satellite", "in-orbit",
        "spacex", "cubesat", "smallsat",
    ],
    "radar_militar": [
        "radar", "aesa", "electronic warfare", " ew ", "jamming", "anti-jam",
        "anti-jamming", "spectrum dominance", "defense", "defence",
        "military", "dod ", "nato", "missile", "surveillance radar", "isr",
        "sigint", "elint", "comint", "tactical radio", "milsatcom",
        "mil-satcom", "gps jamming", "gnss spoofing", "gnss jamming",
        "drone detection", "counter-uas", "counter uas", "c4isr",
        "secure comms", "battlefield", "warfighter", "link 16", "jtrs",
        "passive radar", "isac", "integrated sensing", "jcas",
        "sensing and communication",
    ],
    "radiocom": [
        "amateur radio", "ham radio", " hf ", "vhf", "uhf", "shortwave",
        "sdr", "software defined radio", "software-defined radio",
        "gnu radio", "gnuradio", "rtl-sdr", "hackrf", "dmr", "tetra", " p25",
        "project 25", "land mobile radio", " lmr ", " pmr ", "two-way radio",
        "push-to-talk", " ptt ", "repeater", "ionosphere", "ionospheric",
        "aprs", "packet radio", "ft8", "wspr", "satnogs", "callsign", "qrz",
        "trunked radio", "hf communication",
    ],
    "tv": [
        "broadcast", "broadcaster", "broadcasting", " dvb", "dvb-t", "dvb-t2",
        "dvb-s2", "dvb-c", "atsc", "atsc 3", "nextgen tv", "next-gen tv",
        " ott ", "iptv", "set-top box", " stb ", "cable tv", " catv",
        "hbbtv", " dtt ", " dtv ", "free-to-air", " fta ", "satellite tv",
        " dth ", "direct-to-home", "5g broadcast", "5g-broadcast",
        "transcoding", "video delivery", "headend", "multicast video",
    ],
}

# -------------------------------------------------------------------
# DETECCAO DE PAIS (foco opcional)
# Nome / gentilico / capital + operadoras nacionais + reguladores + satelites.
# Listas propositalmente enxutas para favorecer precisao. Termos de fornecedor
# muito globais (samsung puro, etc.) sao evitados para nao "puxar" demais.
# -------------------------------------------------------------------
COUNTRY_LEXICON = {
    "br": [
        "brazil", "brazilian", "brasil", "anatel", "sao paulo",
        "rio de janeiro", "brasilia", "vivo", "telefonica brasil",
        "claro brasil", "tim brasil", "oi brasil", "grupo oi",
        "embratel", "telebras", "algar telecom", "brisanet",
        "star one", "visiona", "inpe",
    ],
    "ru": [
        "russia", "russian", "moscow", "kremlin", "rostelecom", "megafon",
        "roskomnadzor", "rtrs", "gazprom space",
        "russian satellite communications", "rscc",
    ],
    "il": [
        "israel", "israeli", "tel aviv", "jerusalem", "bezeq", "cellcom",
        "pelephone", "partner communications", "hot mobile", "gilat",
        "ceragon", "amos satellite", "spacecom", "runcom",
    ],
    "in": [
        "india", "indian", "new delhi", "mumbai", "bengaluru",
        "reliance jio", "jio ", "bharti airtel", " airtel", "vodafone idea",
        "bsnl", "mtnl", " trai ", "tata communications", "tejas networks",
        "c-dot", "isro",
    ],
    "jp": [
        "japan", "japanese", "tokyo", "ntt ", "ntt docomo", "docomo", "kddi",
        "softbank", "rakuten mobile", "rakuten", "nec ", "fujitsu", "jsat",
        "sky perfect", "skyperfect", "iown",
    ],
    "kr": [
        "korea", "korean", "south korea", "seoul", "sk telecom", "sktelecom",
        " skt ", "kt corp", "kt corporation", "lg uplus", "lg u+", "lguplus",
        "kt sat", "naver", "samsung electronics",
    ],
    "cn": [
        "china", "chinese", "beijing", "shanghai", "china mobile",
        "china telecom", "china unicom", "huawei", "zte", "miit", "chinasat",
        "china satcom", "spacesail", "qianfan", "guowang", "datang",
        "fiberhome", "caict",
    ],
}

# -------------------------------------------------------------------
# RELEVANCIA (gate de sinal vs ruido) - independe dos temas
# -------------------------------------------------------------------
# Tecnologias e padroes "com nome": ganham bonus quando aparecem no titulo
NAME_TERMS = [
    "5g", "6g", "4g", "lte", "5g-advanced", "5g advanced", "5g-a",
    "open ran", "o-ran", "oran", "vran", "cloud ran", "massive mimo", "mimo",
    "mmwave", "millimeter wave", "sub-6", "c-band", "spectrum",
    "ftth", "fttp", "fttx", "gpon", "xgs-pon", "docsis", "fwa", "fixed wireless",
    "wi-fi 7", "wifi 7", "wi-fi 6", "nb-iot", "lpwan", "lorawan", "lora",
    "volte", "vonr", "vo5g", "network slicing", "private 5g", "private network",
    "cbrs", "small cell", "macro cell", "base station", "gnb", "enb",
    "5gc", "epc", "ims", "sdn", "nfv", "mec", "edge computing",
    "dwdm", "roadm", "coherent optics", "subsea cable", "submarine cable",
    "starlink", "oneweb", "kuiper", "ntn", "atsc", "dvb", "radar", "sdr",
]
# Pesquisa em telecom / processamento de sinais (conta para sinal e para a flag)
RESEARCH_TERMS = [
    "research", "pesquisa", "paper", "arxiv", "study", "we present", "we propose",
    "we introduce", "we show", "method", "approach", "architecture", "framework",
    "algorithm", "scheme", "channel estimation", "channel coding", "ldpc",
    "polar code", "turbo code", "ofdm", "ofdma", "noma", "scma", "waveform",
    "modulation", "qam", "precoding", "beamforming", "spectral efficiency",
    "shannon", "information theory", "capacity region", "bit error",
    "estimation", "detection", "optimization", "convex", "stochastic geometry",
    "ris", "reconfigurable intelligent surface", "irs", "metasurface",
    "thz", "terahertz", "propagation", "path loss", "fading", "channel model",
    "ray tracing", "isac", "integrated sensing", "joint communication",
    "semantic communication", "semantic", "federated learning", "deep learning",
    "neural", "machine learning", "reinforcement learning", "energy efficiency",
    "cell-free", "performance analysis", "benchmark", "millimeter-wave",
]
# Vocabulario geral de telecom + orgaos + fornecedores + operadoras
GENERAL_SIGNAL = [
    "telecom", "telecommunication", "telecommunications", "telecoms",
    "wireless", "mobile", "cellular", "networking", "rf", "radio frequency",
    "antenna", "connectivity", "communications", "comms", "broadband",
    "fiber", "fibre", "optical", "spectrum", "satellite", "satcom",
    "deployment", "rollout", "network", "operator", "carrier", "telco",
    "infrastructure", "interoperability", "backhaul", "fronthaul", "transport",
    # padroes / orgaos
    "3gpp", "itu", "ieee", "etsi", "gsma", "ngmn", "o-ran alliance",
    # fornecedores
    "ericsson", "nokia", "huawei", "zte", "samsung", "qualcomm", "mediatek",
    "cisco", "juniper", "ciena", "corning", "broadcom", "marvell", "nvidia",
    # operadoras
    "verizon", "at&t", "t-mobile", "vodafone", "orange", "telefonica",
    "deutsche telekom", "china mobile", "china telecom", "china unicom",
    "reliance jio", "bharti airtel", "ntt", "kddi", "softbank", "telstra",
]
# Ruido: itens predominantemente sobre isto perdem pontos
NOISE_TERMS = [
    "stock", "share price", "shares", "ipo", "earnings", "dividend",
    "quarterly profit", "lawsuit", "sued", "settlement", "merger talks",
    "acquire", "acquisition", "funding round", "valuation", "ceo", "appoints",
    "hires", "layoff", "layoffs", "resigns", "crypto", "bitcoin", "blockchain",
    "phone review", "best phone", "smartphone deal", "iphone deal",
    "android deal", "discount", "coupon", "promo code", "best plan",
    "cheapest plan", "unlimited plan", "black friday", "prime day", "best deal",
    "streaming deal", "tv deal", "how to watch", "vpn deal", "gift guide",
]

# -------------------------------------------------------------------
# CASAMENTO POR LIMITE DE "PALAVRA"
# Usa lookarounds (?<![a-z0-9]) ... (?![a-z0-9]) para que termos curtos so
# casem isolados: "ses" casa SES mas nao "uses"; "pon" nao casa "coupon";
# "iot" nao casa "patriot"; "5g" casa em "5g-advanced" mas nao em "5gc".
# Espacos de padding nas listas sao removidos (o limite ja cuida da borda).
# -------------------------------------------------------------------
_BL = r"(?<![a-z0-9])"
_BR = r"(?![a-z0-9])"


def make_matchers(terms):
    out, seen = [], set()
    for t in terms:
        t = (t or "").strip().lower()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(re.compile(_BL + re.escape(t) + _BR))
    return out


# conjunto unico de sinal (evita contagem dupla do mesmo termo)
_signal_all = list(NAME_TERMS) + list(RESEARCH_TERMS) + list(GENERAL_SIGNAL)
for _terms in THEME_LEXICON.values():
    _signal_all += _terms

NAME_M = make_matchers(NAME_TERMS)
RESEARCH_M = make_matchers(RESEARCH_TERMS)
NOISE_M = make_matchers(NOISE_TERMS)
SIGNAL_M = make_matchers(_signal_all)
THEME_M = {k: make_matchers(v) for k, v in THEME_LEXICON.items()}
COUNTRY_M = {c: make_matchers(v) for c, v in COUNTRY_LEXICON.items()}


def norm(s):
    return (s or "").strip()


def clean_text(s, limit=320):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)          # tira tags
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] + "..."
    return s


def count_matches(text, matchers):
    """Conta quantos padroes (com limite de palavra) casam no texto.

    Usa os casadores compilados em make_matchers, e nao substring cru, para
    evitar falso-positivo: 'roadmap' nao casa 'roadm', 'patriot' nao casa
    'iot', 'paris' nao casa 'ris', 'coupon' nao casa 'pon'.
    """
    return sum(1 for rx in matchers if rx.search(text))


def classify_themes(blob, force_sat):
    """Retorna a lista de temas (>= 1). 'geral' eh o balde de quem sobra."""
    themes = []
    for key, matchers in THEME_M.items():
        if any(rx.search(blob) for rx in matchers):
            themes.append(key)
    if force_sat and "satelite" not in themes:
        themes.append("satelite")
    if not themes:
        themes.append("geral")
    return themes


def detect_countries(blob):
    """Retorna os codigos de pais citados (pode ser vazio)."""
    out = []
    for cc, matchers in COUNTRY_M.items():
        if any(rx.search(blob) for rx in matchers):
            out.append(cc)
    return out


def analyze(title, summary, src):
    """Retorna (relevancia 0-100, temas, eh_pesquisa, paises)."""
    blob = (" " + title + " " + summary + " ").lower()

    signal = count_matches(blob, SIGNAL_M)
    name_hits = count_matches(blob, NAME_M)
    research_hits = count_matches(blob, RESEARCH_M)
    noise = count_matches(blob, NOISE_M)

    raw = signal * 4 + name_hits * 5 + research_hits * 4 - noise * 6
    raw = raw * src["weight"]
    # titulo carrega mais peso: nomes de tecnologia no titulo dao bonus
    if count_matches(" " + title.lower() + " ", NAME_M):
        raw += 14
    # curva saturante: da boa variacao no medidor sem todo mundo bater 100
    relevance = 0 if raw <= 0 else int(round(100 * raw / (raw + 35.0)))

    force_sat = src.get("region") == "satellite"
    themes = classify_themes(blob, force_sat)
    is_research = (src.get("kind") == "research") or (research_hits >= 3)
    countries = detect_countries(blob)
    return relevance, themes, is_research, countries


def parse_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return dt.datetime.fromtimestamp(time.mktime(val), tz=dt.timezone.utc)
            except Exception:
                pass
    return None


def fetch(url, timeout=25):
    """Baixa o feed com User-Agent (alguns servidores bloqueiam o default)."""
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; Telecom-Radar/1.0; +github-pages)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now - dt.timedelta(days=45)
    items = []
    seen = set()
    report = []

    for src in SOURCES:
        ok, kept = 0, 0
        try:
            raw = fetch(src["url"])
            feed = feedparser.parse(raw)
            entries = feed.entries or []
            ok = len(entries)
        except (URLError, HTTPError, Exception) as e:
            report.append({"source": src["name"], "status": f"ERRO: {e}", "kept": 0})
            print(f"[!] {src['name']}: {e}", file=sys.stderr)
            continue

        per_src = []
        for e in entries:
            title = clean_text(e.get("title", ""), 240)
            link = norm(e.get("link", ""))
            if not title or not link:
                continue

            key = hashlib.md5(re.sub(r"[^a-z0-9]", "", title.lower()).encode()).hexdigest()
            if key in seen:
                continue

            summary = clean_text(e.get("summary", "") or e.get("description", ""))
            date = parse_date(e)
            if date and date < horizon:
                continue

            relevance, themes, is_research, countries = analyze(title, summary, src)

            # filtro de "noticia a toa": fontes amplas precisam cruzar o limiar
            if src["strict"] and relevance < 40:
                continue
            if relevance < 20:
                continue

            seen.add(key)
            per_src.append({
                "title": title,
                "link": link,
                "summary": summary,
                "source": src["name"],
                "themes": themes,
                "research": is_research,
                "countries": countries,
                "relevance": relevance,
                "date": date.isoformat() if date else None,
                "ts": date.timestamp() if date else 0,
            })

        # ordena por relevancia dentro da fonte e aplica o cap
        per_src.sort(key=lambda x: (x["relevance"], x["ts"]), reverse=True)
        per_src = per_src[: src["cap"]]
        kept = len(per_src)
        items.extend(per_src)
        report.append({"source": src["name"], "status": f"ok ({ok} itens)", "kept": kept})
        print(f"[+] {src['name']}: {ok} lidos, {kept} mantidos")

    # ordenacao final: mais recentes e relevantes no topo
    items.sort(key=lambda x: (x["ts"], x["relevance"]), reverse=True)
    items = items[:260]

    theme_counts = {k: sum(1 for i in items if k in i["themes"])
                    for k in list(THEME_LEXICON.keys()) + ["geral"]}
    country_counts = {c: sum(1 for i in items if c in i["countries"])
                      for c in COUNTRY_LEXICON.keys()}
    research_count = sum(1 for i in items if i["research"])

    payload = {
        "generated_at": now.isoformat(),
        "count": len(items),
        "theme_counts": theme_counts,
        "country_counts": country_counts,
        "research_count": research_count,
        "sources": report,
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nOK -> {OUT} ({len(items)} itens, {research_count} de pesquisa)")
    print("temas:", theme_counts)
    print("paises:", country_counts)


if __name__ == "__main__":
    main()
