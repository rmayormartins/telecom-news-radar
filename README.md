# TELECOM RADAR

Monitor de noticias de telecomunicacoes focado em **sinal sobre ruido**, com filtros
por **tema** (moveis, fibra, antenas, IoT, satelite, radar/militar, radiocom, TV),
**foco por pais** (Brasil, Russia, Israel, India, Japao, Coreia, China) e uma chave para
**ocultar a pesquisa** (arXiv/papers). Pagina unica, estatica, servida pelo GitHub
Pages. A coleta roda sozinha via GitHub Actions.

Sem framework, sem build, sem Vercel. So `index.html` + um JSON gerado por um script Python.

> Mesma arquitetura do [ai-news-radar](https://github.com/rmayormartins/ai-news-radar),
> reaproveitada para o universo de telecom: logo em vermelho, classificacao por tema,
> foco por pais e chave de pesquisa no lugar das faixas originais.

## Como funciona

```
GitHub Actions (cron 6/6h)
        |
        v
scripts/fetch_news.py  ->  le feeds RSS, pontua relevancia, classifica, deduplica
        |
        v
data/news.json  (commitado no repo)
        |
        v
index.html  (fetch do JSON, renderiza no navegador)  ->  GitHub Pages
```

A coleta acontece no servidor (Action), entao nao ha problema de CORS: a pagina so le um
arquivo JSON do proprio repositorio.

## Estrutura

```
index.html                          frontend (single-file, zero dependencia)
data/news.json                      dados gerados (seed inicial incluso)
scripts/fetch_news.py               coletor e curador
.github/workflows/update-news.yml   automacao (cron + manual)
```

## Publicar (GitHub Pages)

1. Suba os arquivos para um repositorio (ex: `telecom-news-radar`), branch `main`.
2. **Settings -> Pages -> Build and deployment -> Source: Deploy from a branch**,
   branch `main`, pasta `/ (root)`. Salve.
3. **Settings -> Actions -> General -> Workflow permissions:** marque
   **Read and write permissions** (a Action precisa commitar o `news.json`).
4. Aba **Actions -> update-news -> Run workflow** para fazer a primeira coleta real
   (ou espere o cron). A pagina sai em `https://SEU_USUARIO.github.io/telecom-news-radar/`.

Ate a primeira coleta, a pagina mostra um seed de exemplos e um aviso para rodar o workflow.

## Temas, foco por pais e pesquisa

Cada noticia recebe **um ou mais temas** (multi-rotulo) por palavra-chave:

- **Moveis:** 5G/6G, LTE, RAN, Open RAN, nucleo, espectro movel, operadora.
- **Fibra:** FTTH, PON (GPON/XGS-PON), backbone, transporte optico, banda larga fixa.
- **Antenas:** antena, MIMO, beamforming, array, propagacao, RF front-end.
- **IoT:** NB-IoT, LoRa/LoRaWAN, LPWAN, M2M, smart metering, IIoT, sensores.
- **Satelite:** NTN, LEO/GEO, Starlink, direct-to-cell, estacao terrena, satcom.
- **Radar/Militar:** radar, guerra eletronica, anti-jamming, counter-UAS, defesa.
- **Radiocom:** SDR, radioamadorismo, HF/VHF/UHF, TETRA/P25, two-way radio.
- **TV:** broadcast, ATSC/DVB, NextGen TV, video over IP, radiodifusao.
- **Geral:** balde de quem nao casou com nenhum tema acima.

Os temas funcionam como **chaves**: clique em um ou varios e o feed mostra a **uniao**
deles (nenhum selecionado = todos). O painel **Foco por pais** faz o mesmo para Brasil,
Russia, Israel, India, Japao, Coreia e China (deteccao por nome do pais, operadoras e
fabricantes locais). A chave **ocultar pesquisa** tira os papers (arXiv) de qualquer recorte.

Os paineis sao montados a partir do proprio `news.json`: se voce criar um tema novo no
coletor, ele aparece sozinho no painel (cor e rotulo caem num padrao neutro ate voce
definir um estilo). Os contadores ao lado de cada tema/pais mostram quantos itens ha no
recorte atual.

Cada card tras um medidor **SNR** (relevancia estimada de 0 a 100). Da pra buscar por texto
(tecnologia, operadora, pais), filtrar por fonte e ordenar por recencia ou relevancia.
Tem ainda um botao **traduzir** (EN -> PT) que roda no proprio navegador.

## Filtro de relevancia (o "sinal sobre ruido")

`fetch_news.py` pontua cada item por palavras-chave (tecnologias e padroes, termos de
implantacao e de pesquisa) e penaliza ruido (acoes, processos, M&A, fofoca de CEO, ofertas de
plano/aparelho). Feeds amplos (imprensa) so entram se cruzarem o limiar; feeds tecnicos e de
padroes entram direto. Assim voce nao recebe "qualquer noticia de telecom a toa".

## Customizar

**Fontes:** edite a lista `SOURCES` no topo de `scripts/fetch_news.py`. Cada fonte tem:

- `region`: `"ground"` (terrestre) ou `"satellite"` (satcom)
- `weight`: peso da fonte na relevancia (padroes e pesquisa valem mais)
- `strict`: se `True`, so entra item acima do limiar (use em feeds amplos)
- `cap`: maximo de itens por fonte por rodada

**Temas e paises:** edite `THEME_LEXICON` (palavras-chave de cada tema) e `COUNTRY_LEXICON`
(nomes e operadoras por pais) em `scripts/fetch_news.py`. Para um tema novo, basta adicionar
uma entrada no dicionario: ele entra no JSON e aparece no painel automaticamente.

**Limiares e lexico de relevancia:** ajuste `NAME_TERMS` (tecnologias/padroes/operadoras),
`GENERAL_SIGNAL`, `RESEARCH_TERMS`, `NOISE_TERMS` e os cortes de relevancia
(`relevance < 40` para strict, `< 20` geral) na funcao `analyze`.

**Frequencia:** mude o `cron` em `.github/workflows/update-news.yml`.

## Rodar local

```
pip install feedparser
python scripts/fetch_news.py        # gera data/news.json
python -m http.server 8000          # abra http://localhost:8000
```

Abrir o `index.html` direto pelo `file://` funciona com o seed embutido, mas para ler o
`news.json` o navegador exige um servidor (qualquer um serve).

## Fontes incluidas

Imprensa / industria: Light Reading, Fierce Network, Telecoms.com, RCR Wireless, Mobile World
Live, TelecomTV, Telecompetitor, The Fast Mode, Total Telecom, TeckNexus, Telecoms Tech News,
CircleID, DataCenterDynamics, Capacity Media, Telecom Lead.

Tecnologia / padroes: 3G4G Blog, IEEE Spectrum (Telecom), Ericsson, Nokia, IEEE ComSoc Tech Blog,
One6G, 6G-IA, 6GWorld, 3GPP, ETSI.

Pesquisa (arXiv): eess.SP (processamento de sinais), cs.NI (redes), cs.IT (teoria da informacao),
eess.SY (sistemas e controle).

Regulatorio: FCC.

Satelite (satcom): SpaceNews, Via Satellite, Advanced Television, SatNews, European Spaceflight.

Feeds que saem do ar sao ignorados sem quebrar a coleta. Veja `sources` no `news.json` para o
status de cada um na ultima rodada, e ajuste a URL se alguma fonte mudar de endereco.

## Licenca

MIT.
