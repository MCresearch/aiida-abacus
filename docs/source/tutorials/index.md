# Tutorials

This page show how to work with AiiDA and run a simple ABACUS calculation using the computer, code, and pseudo potential family we configured.

(tutorials-quick-start)=

## Quick start

:::{attention}
**No time to install?**  
Click the Binder badge [![Binder][binder-badge]][binder-link] to launch a **zero-install** JupyterLab.  
In two minutes you’ll have AiiDA + ABACUS fully set-up—complete with ready-to-run notebooks that let you submit calculations, track provenance, and visualize results right in your browser.
:::

## Run locally

To start locally:

1. First we will configure the [AiiDA](https://www.aiida.net/) environment. A computer and the corresponding code will be set available.

    We provide an easy installation and configuration guide for a **local ABACUS LTSv3.10.0/Ubuntu** calculation with `Pseudo-Dojo v0.4` here. You can follow the guide or skip if some steps are already done. Adapt the configuration to suit your tastes.

    :::{tip}
    ### Quick one-command install
    If you simply want everything ready on **Ubuntu/WSL**, run once:
    ```console
    $ sudo apt update
    $ xargs -a .binder/apt.txt sudo apt install -y      # system deps
    $ conda create -n aiida python=3.10 -y && conda activate aiida
    $ bash .binder/postBuild                            # 5-stage automatic setup            
    ```
    The script performs the following stages — each can also be executed manually if you prefer full control.
    :::

    0. It is recommended to use a virtual environment.
    ```console
    $ conda create -n aiida python=3.10 -y
    $ conda activate aiida
    ```

    1. Install system dependencies (Ubuntu)
    ```console
    $ sudo apt update
    $ xargs -a .binder/apt.txt sudo apt install -y      # system deps
    ```

    2. Install Python packages.
    ```console
    $ pip install -e .
    $ pip install pymatgen ase-weas-widget aiida-vasp sumo
    ```

    3. Build ABACUS **LTSv3.10.0**.
    ```bash
    $ git clone https://github.com/deepmodeling/abacus-develop.git
    $ cd abacus-develop
    $ git checkout LTSv3.10.0
    $ cmake -B build \
        -DCMAKE_INSTALL_PREFIX=$PWD \
        -DENABLE_RAPIDJSON=ON
        cmake --build build -j$(nproc)
        cmake --install build
    ```
    This compiles ABACUS with LibXC and LibRI support and places the binary at `abacus-develop/bin/abacus`.
    You can use your local ABACUS directly.

    4. Initialize AiiDA
    ```console
    $ verdi presto
    ```
    Creates a lightweight AiiDA profile using SQLite and localhost (no RabbitMQ required for the tutorial).

    5. Register the ABACUS code
    ```bash
    $ verdi code create core.code.installed -n \
        -Y localhost -L abacus \
        -D "ABACUS LTSv3.10.0" -P abacus.abacus \
        -X $(pwd)/abacus-develop/bin/abacus
    ```
    Adds the freshly built executable to AiiDA as `abacus@localhost`.

    6. Install pseudopotentials and finalize
    ```bash
    $ aiida-pseudo install pseudo-dojo -f upf
    $ verdi -p presto computer configure core.local localhost \
        -n --no-use-login-shell --safe-interval 1
    ```
    Downloads the **Pseudo-Dojo v0.4 PBE SR standard UPF** family and configures the localhost computer to suppress login-shell artifacts.


See [Installation — AiiDA documentation](https://aiida.readthedocs.io/projects/aiida-core/en/latest/installation/index.html) for a complete installation guide.


After these steps, we're ready to submit our first calculation.

---

2. Activate the AiiDA virtual environment.

```console
$ conda activate aiida
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

4. Check the code and pseudopotential families used in the calculation.
    
    :::{note}
    Check installed code by

    ```console
    $ abacus -v
    ABACUS version v3.10.0
    $ verdi code list
    Full label                   Pk  Entry point
    -----------------------  ------  -------------------
    abacus@localhost              2  core.code.installed
    $ verdi code test abacus@localhost
    Success: all tests succeeded.
    ```

    Check installed pseudos by  

    ```console
    $ verdi group list -a
      PK  Label                                                                                Type string                User
    ----  -----------------------------------------------------------------------------------  -------------------------  ---------------
    1  PseudoDojo/0.4/PBE/SR/standard/upf                                                   pseudo.family.pseudo_dojo  aiida@localhost
    ```

    :::

<!-- :::{important}
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
Label                               Type string                Count
----------------------------------  -------------------------  -------
PseudoDojo/0.4/PBE/SR/standard/upf  pseudo.family.pseudo_dojo  72
$ abacus -v
ABACUS version v3.10.0
```
::: -->

5. Now let us run an example script. It will submit the ABACUS calculation.
    ```console
    $ verdi run examples/example_pw_Si2.py
    ```

6. Inspect the calculation progress:
    ```console
    $ verdi process list -a
        PK  Created    Process label      ♻    Process State    Process status
    ------  ---------  -----------------  ---  ---------------  ----------------
    233  5m ago     AbacusCalculation       ⏹ Finished [0]
    ```

7. Now let's check the report for this process: (Replace 233 with the PK shown in the previous step and run)
    ```console
    $ verdi process report 233
    ```
    It will present a log report of the process.
    To investigate more about the calculation, like raw inputs/outputs, see the [How To Check the results](#howto-check) page for details.


:::{note}
AiiDA supports many different schedulers apart from Direct Execution.
If you are using a Batch Job Scheduler like [SLURM](https://slurm.schedmd.com/) to manage the job queues and execution on a compute resource, see supported
[Batch Job Schedulers](https://aiida.readthedocs.io/projects/aiida-core/en/latest/topics/schedulers.html).
:::

[binder-badge]: https://mybinder.org/badge_logo.svg
[binder-link]: https://mybinder.org/v2/gh/MCresearch/aiida-abacus/HEAD?urlpath=%2Fdoc%2Ftree%2Fexamples%2Fbinder-example.ipynb