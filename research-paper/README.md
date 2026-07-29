# Ulap research papers

An index of the research papers this codebase supports. Paper sources and build
files live in a separate repository; this page is the citable record of what has
been published and where to find it.

Full text is **not** mirrored here. Follow the arXiv links.

## Published

| # | Paper | Authors | Published | arXiv | Primary category | DOI |
|---|---|---|---|---|---|---|
| 1 | **SIDSense: Database-Free TV White Space Sensing for Disaster-Resilient Connectivity** | George M. Gichuru, Zoe Aiyanna M. Cayetano | 14 Feb 2026 | [arXiv:2602.13542v1](https://arxiv.org/abs/2602.13542v1) | cs.NI | [10.48550/arXiv.2602.13542](https://doi.org/10.48550/arXiv.2602.13542) |

### 1. SIDSense

- **Title:** SIDSense: Database-Free TV White Space Sensing for Disaster-Resilient Connectivity
- **Authors:** George M. Gichuru, Zoe Aiyanna M. Cayetano
- **Submitted:** 14 February 2026
- **arXiv:** [2602.13542v1](https://arxiv.org/abs/2602.13542v1)
- **Categories:** cs.NI (primary), cs.DC (cross-list)
- **DOI:** [10.48550/arXiv.2602.13542](https://doi.org/10.48550/arXiv.2602.13542)

> Small Island Developing States (SIDS) are disproportionately exposed to
> climate-driven disasters, yet often rely on fragile terrestrial networks that
> fail when they are most needed. TV White Space (TVWS) links offer long-range,
> low-power coverage; however, current deployments depend on Protocol to Access
> White Spaces (PAWS) database connectivity for channel authorization, creating a
> single point of failure during outages. We present SIDSense, an edge AI
> framework for database-free TVWS operation that preserves regulatory intent
> through a compliance-gated controller, audit logging, and graceful degradation.
> SIDSense couples CNN-based spectrum classification with a hybrid sensing-first,
> authorization-as-soon-as-possible workflow and co-locates sensing and video
> enhancement with a private 5G stack on a maritime vessel to sustain
> situational-awareness video backhaul. Field experiments in Barbados demonstrate
> sustained connectivity during simulated PAWS outages, achieving 94.2% sensing
> accuracy over 470-698 MHz with 23 ms mean decision latency, while maintaining
> zero missed 5G Layer-1 (L1) deadlines under GPU-aware scheduling. We release an
> empirical Caribbean TVWS propagation and occupancy dataset and look to
> contribute some of the components of the SIDSense pipeline to the open source
> community to accelerate resilient connectivity deployments in climate-vulnerable
> regions.

**BibTeX**

```bibtex
@misc{gichuru2026sidsense,
  title         = {SIDSense: Database-Free TV White Space Sensing for Disaster-Resilient Connectivity},
  author        = {Gichuru, George M. and Cayetano, Zoe Aiyanna M.},
  year          = {2026},
  eprint        = {2602.13542},
  archivePrefix = {arXiv},
  primaryClass  = {cs.NI},
  doi           = {10.48550/arXiv.2602.13542},
  url           = {https://arxiv.org/abs/2602.13542}
}
```

## In preparation

Not yet published. Listed for transparency about what this codebase is being
written up for. Do not cite until an arXiv identifier exists.

| # | Working title | Authors | Status |
|---|---|---|---|
| 2 | Sovereign Cognitive Digital Twins: Fusing 6G ISAC, AI-RAN, and Zero-Trust Edge Grids | Zoe Aiyanna M. Cayetano, Taijuo Morris, George M. Gichuru | Under internal review; submission to arXiv cs.NI planned |

This repository is the reference implementation for paper #2. When it is
announced, this table and `CITATION.cff` are updated with the arXiv ID and DOI.

## Which code backs which paper

| Paper | Relevant code |
|---|---|
| #1 SIDSense | Not in this repository — TVWS sensing stack lives separately |
| #2 S-CDT / 6G-ISAC | This repository: [`ulap-scope/`](../ulap-scope/) pipeline (including the Blender/Mitsuba scene-build and Sionna RT stages under [`ulap-scope/ulap_scope/stages/`](../ulap-scope/ulap_scope/stages/)), and [`docs/renders/`](../docs/renders/) result figures — each mapped to the command that produced it in [`docs/renders/README.md`](../docs/renders/README.md) |

> `blender/` is a *working directory*, not source: the pipeline writes scenes and
> results into it at run time and its contents are not tracked (see
> [DATA.md](../DATA.md)). The code that backs the paper lives in `ulap-scope/`.

## Citing this software

Cite the software itself with [`CITATION.cff`](../CITATION.cff) in the repository
root, and the paper separately using the BibTeX above. GitHub renders a "Cite
this repository" button from the CFF file.
