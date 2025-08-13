---
myst:
  substitutions:
    README.md of the repository: '`README.md` of the repository'
    aiida-core documentation: '`aiida-core` documentation'
    aiida-abacus: '`aiida-abacus`'
---

```{toctree}
:hidden: true
:caption: Getting started

installation/index
tutorials/index
```

```{toctree}
:hidden: true
:caption: How to

howto/check/index

```
<!-- howto/calculations/index
howto/workflows/index -->

<!-- ```{toctree}
:hidden: true
:caption: Developer Guide

developer_guide/index
``` -->

<!-- ```{toctree}
:hidden: true
:caption: Topic guides
topics/calculations/index
topics/workflows/index
``` -->


<!-- ```{toctree}
:hidden: true
:caption: Reference

``` -->
<!-- ```{toctree}
:hidden: true
:caption: Reference
reference/api/index
reference/cli/index
``` -->

# AiiDA-ABACUS

Welcome to the documentation of `AiiDA-ABACUS`!

An AiiDA plugin package for the [**ABACUS**](https://github.com/deepmodeling/abacus-develop) DFT package.
Automate large-scale electronic-structure calculations with full data provenance, high-throughput workflows, and effortless remote-machine integration powered by AiiDA.
<!-- Automate large-scale electronic-structure calculations, geometry optimisations, band structures and more—**with full data provenance** provided by AiiDA. -->

<!-- [![PyPI version](https://badge.fury.io/py/aiida-abacus.svg)](https://badge.fury.io/py/aiida-abacus)
[![Python versions](https://img.shields.io/pypi/pyversions/aiida-abacus.svg)](https://pypi.org/project/aiida-abacus/)
[![CI](https://github.com/MCresearch/aiida-abacus/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/MCresearch/aiida-abacus/actions)
[![Docs](https://readthedocs.org/projects/aiida-abacus/badge/)](https://aiida-abacus.readthedocs.io) -->


<!-- AiiDA-ABACUS is under development. Please check the GitHub repo for latest info. -->

## How to cite

If you use the `aiida-abacus` plugin in your research, please cite:

- The AiiDA paper  
  > Huber, S.P., Zoupanos, S., Uhrin, M. et al. AiiDA 1.0, a scalable computational infrastructure for automated reproducible workflows and data provenance. Sci Data 7, 300 (2020).
  [DOI:10.1038/s41597-020-00638-4](https://doi.org/10.1038/s41597-020-00638-4)
  <!-- > Sebastiaan P. Huber _et al._, *AiiDA 1.0: a scalable computational infrastructure for automated reproducible workflows and data provenance*, **Scientific Data 7**, 300 (2020).   -->
  
  > Uhrin, Martin & Huber, Sebastiaan & Yu, Jusong & Marzari, Nicola & Pizzi, Giovanni. . Workflows in AiiDA: Engineering a high-throughput, event-based engine for robust and modular computational workflows. Computational Materials Science. 187(2021). 
  [DOI:110086.10.1016/j.commatsci.2020.110086](http://dx.doi.org/10.1016/j.commatsci.2020.110086)
  <!-- 110086.10.1016/j.commatsci.2020.110086.  -->


- The ABACUS program paper
  - See [ABACUS Home](https://abacus.ustc.edu.cn/main.htm).
  
## Note

Please note that if you encounter any troubles with ABACUS itself, consult the [ABACUS documentation](https://abacus.deepmodeling.com/) or [Github Pages](https://mcresearch.github.io/abacus-user-guide/) for more tutorials and developer guides.

If you run into any issues while using the plugin, spot a bug, need a new feature, or simply see room for improvement, please [open an issue](https://github.com/MCresearch/aiida-abacus/issue) or—even better—[submit a pull request](https://github.com/MCresearch/aiida-abacus/pulls) to address it. 

If you’re interested in contributing to the [`aiida-abacus`](https://github.com/MCresearch/aiida-abacus) project, please open an issue first so we can discuss how best to proceed; all community contributions are warmly welcomed.
