# Tutorials

This page show how to run a simple ABACUS calculation using the computer, code, and pseudo potential family we configured.

1. First we will configure the [AiiDA](https://www.aiida.net/) environment. A computer and the corresponding code will be set available.

We provide an easy installation and configuration guide here.





See [AiiDA installation guide](https://aiida.readthedocs.io/projects/aiida-core/en/latest/installation/index.html) for more information.

2. Activate the AiiDA virtual environment.
, for example run `conda activate aiida-env` or suchlike.
```console
$ conda activate aiida-env
```

3. Start the daemon.
    ```console
    $ verdi daemon start
    ```
    Check that the `daemon` is running:
    ```console
    $ verdi daemon status
    Daemon is running as PID xxxxxxx since yyyy-MM-dd HH:mm:ss
    Active workers [1]:
        PID    MEM %    CPU %  started
    -------  -------  -------  -------------------
    xxxxxxx    0.159        0  yyyy-MM-dd HH:mm:ss
    Use `verdi daemon [incr | decr] [num]` to increase / decrease the number of workers
    ```

4. Install the code and pseudopotential families used in the calculation.

    We will use an ABACUS LTSv3.10.0 code at locolhost as example.
    
    1. First install ABACUS and configure the code by AiiDA.
    We provide a simple installation and configure script on localhost here. Please consult [ABACUS Easy Installation](https://abacus.deepmodeling.com/en/latest/quick_start/easy_install.html) for details.


    :::{note}
    Check installed code by

    ```console
    $ verdi code list
    Full label                   Pk  Entry point
    -----------------------  ------  -------------------
    abacus@localhost              2  core.code.installed
    $ verdi code test abacus@localhost
    Success: all tests succeeded.
    ```
    :::

    2. Then And the calculation uses `PseudoDojo/0.4/PBE/SR/standard/upf`.

    ```console
    $ aiida-pseudo install pseudo-dojo -f upf -v 0.4 -x PBE -r SR -p standard
    ```

    :::{note}
    Check installed pseudos by  

    ```console
    $ verdi group list -a
      PK  Label                                                                                Type string                User
    ----  -----------------------------------------------------------------------------------  -------------------------  ---------------
    1  PseudoDojo/0.4/PBE/SR/standard/upf                                                   pseudo.family.pseudo_dojo  aiida@localhost
    ```
    :::

:::{important}
Make sure that all the environments are ready here before we start the calculation:
- [aiida-core](https://aiida.readthedocs.io/projects/aiida-core/en/stable/installation/guide_quick.html) configured.

- `aiida-abacus` installed. (See [Installation guide](#installation-install))

- [`aiida-pseudo`](https://aiida-pseudo.readthedocs.io/en/latest/) package and `pseudo-dojo` family installed.

- `abacus` executable ready.

Please activate your AiiDA environment and run the checks:

```console
$ verdi status
$ verdi plugin list aiida.calculations abacus.abacus
$ aiida-pseudo list -F pseudo.family.pseudo_dojo
$ abacus -v # should give: ABACUS version v3.10.0
```
:::

5. Now run `examples/launch.py`. It will submit the ABACUS calculation.
    ```console
    $ verdi run examples/launch.py
    ```

6. Inspect the calculation progress:
    ```console
    $ verdi process list -a
        PK  Created    Process label      ♻    Process State    Process status
    ------  ---------  -----------------  ---  ---------------  ----------------
    233  5m ago     AbacusCalculation       ⏹ Finished [0]
    ```

7. Now let's check the report for this process:
    ```console
    $ verdi process report 233
    ```
    It will present a log report of the process.
    To investigate more about the calculation, like raw inputs/outputs, see the [How To Check the results](#howto-check) page for details.