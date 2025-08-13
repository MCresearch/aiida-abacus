# Tutorials

This page show how to run a simple ABACUS calculation using the computer, code, and pseudo potential family we configured before.

1. First please ensure your [AiiDA](https://www.aiida.net/) environment is properly configured. Configure the computer and code.

2. Activate the AiiDA virtual environment.
, for example run `conda activate aiida-env` or suchlike.
<!-- ```console
$ conda activate aiida
``` -->

3. Check the code and install pseudopotential families used in the calculation.

We will use an ABACUS LTSv3.10.0 code at locolhost as example.
```console
$ verdi code test abacus-3.10.0@locolhost
```

And the calculation uses `PseudoDojo/0.4/PBE/SR/standard/upf`.

```console
$ aiida-pseudo install pseudo-dojo -f upf -v 0.4 -x PBE -r SR -p standard
```