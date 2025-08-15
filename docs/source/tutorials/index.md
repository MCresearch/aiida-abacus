# Tutorials

:::{important}
Before we start the tour, make sure that all the environments are ready:
- [aiida-core](https://aiida.readthedocs.io/projects/aiida-core/en/stable/installation/guide_quick.html) configured.

- `aiida-abacus` installed. (See [Installation guide](#installation-install))

- [`aiida-pseudo`](https://aiida-pseudo.readthedocs.io/en/latest/) package and `pseudo-dojo` family installed.

- `abacus` executable ready.

:::

This page show how to run a simple ABACUS calculation using the computer, code, and pseudo potential family we configured before.

1. First please ensure your [AiiDA](https://www.aiida.net/) environment is properly configured. A computer and the corresponding code should be available.

2. Activate the AiiDA virtual environment.
, for example run `conda activate aiida-env` or suchlike.
<!-- ```console
$ conda activate aiida
``` -->

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

4. Check the code and install pseudopotential families used in the calculation.

    We will use an ABACUS LTSv3.10.0 code at locolhost as example.
    ```console
    $ verdi code test abacus-3.10.0@locolhost
    ```

    And the calculation uses `PseudoDojo/0.4/PBE/SR/standard/upf`.

    ```console
    $ aiida-pseudo install pseudo-dojo -f upf -v 0.4 -x PBE -r SR -p standard
    ```

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