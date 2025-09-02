# Tutorials

This page show how to work with AiiDA and run a simple ABACUS calculation using the computer, code, and pseudo potential family we configured.

(tutorials-quick-start)=

## Quick start

:::{attention}
**No time to install?**  
Click the Binder badge [![Binder][binder-badge]][binder-link] to launch a **zero-install** JupyterLab.  
In two minutes you’ll have AiiDA + ABACUS fully set-up—complete with ready-to-run notebooks that let you submit calculations, track provenance, and visualize results right in your browser.
:::

You can also run `binder-example.ipynb` in the `examples` directory locally for a glimpse into `aiida-abacus`.

## Run locally

To start locally, we'll set up both [AiiDA](https://www.aiida.net/sections/download.html) environment and [ABACUS](https://github.com/deepmodeling/abacus-develop).

We provide an easy installation and configuration guide for a **local ABACUS LTSv3.10.0** tested on **Ubuntu 22.04 LTS** calculation with `Pseudo-Dojo v0.4` here. You can follow the guide or skip if some steps are already done. Adapt the configuration to suit your tastes.

First you should choose one package manager like `conda`, `uv`, and then install packages with it.


### Prerequisites

#### 1. Package manager installation

It is recommended to use a virtual environment, like [conda](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html) and [uv](https://docs.astral.sh/uv/).
To install if you have not already had one, run the following command(see [conda install](https://www.anaconda.com/docs/getting-started/miniconda/install#linux-2) and [uv installation](https://docs.astral.sh/uv/getting-started/installation/)):


::::{tab-set}

:::{tab-item} conda
Install Miniconda:
```console
$ mkdir -p ~/miniconda3
$ wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh
$ bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
$ rm ~/miniconda3/miniconda.sh
```
After installing, close and reopen your terminal application or refresh it by running the following command:
```console
$ source ~/miniconda3/bin/activate
```
Finally initialize conda on all available shells:
```console
$ conda init --all
```
:::

:::{tab-item} uv (faster alternative)
Install uv with one single line:
```console
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```
If installing from PyPI:
```console
$ pipx install uv
```
And `pip` can also be used:
```console
$ pip install uv
```
:::
::::

Next we will setup AiiDA & ABACUS.

::::{tab-set}

:::{tab-item} Starting from scratch
If you're new to both AiiDA and ABACUS, follow this complete setup:
:::

:::{tab-item} Already have ABACUS?
If you already have ABACUS compiled, skip to [AiiDA setup](#aiida-setup).
:::

:::{tab-item} Already have AiiDA?
If you already have an AiiDA environment, skip to [ABACUS compilation](#compile-abacus).
:::
::::



:::::{tip}
#### Quick one-command install

If you simply want everything ready on **Ubuntu/WSL**, run once:

::::{tab-set}
:::{tab-item} conda
<!-- If you simply want everything ready on **Ubuntu/WSL**, run once (with conda as package manager): -->
```console
$ git clone https://github.com/MCresearch/aiida-abacus.git
$ cd aiida-abacus
$ sudo apt update
$ xargs -a .binder/apt.txt sudo apt install -y      # system deps
$ conda create -n aiida python=3.10 -y && conda activate aiida
$ bash .binder/postBuild          # 5-stage automatic setup
```
:::
:::{tab-item} uv
<!-- If you simply want everything ready on **Ubuntu/WSL**, run once (with uv as package manager): -->
```console
$ git clone https://github.com/MCresearch/aiida-abacus.git
$ cd aiida-abacus
$ sudo apt update
$ xargs -a .binder/apt.txt sudo apt install -y      # system deps
$ uv sync --extra tutorial
$ source .venv/bin/activate
$ bash .binder/postBuild          # 5-stage automatic setup
```
:::
::::

The script performs the following stages — each can be executed manually if you prefer full control.
:::::

<!-- $ source ~/.bashrc  # or restart your terminal -->


(aiida-setup)=

#### 2. AiiDA environment setup

Now let's install Python packages needed.

::::{tab-set}

:::{tab-item} conda
```console
$ conda create -n aiida python=3.10 -y
$ conda activate aiida
$ cd aiida-abacus
$ pip install -e .
$ pip install pymatgen ase-weas-widget aiida-vasp sumo
```
> Packages will be installed into the named env `~/miniconda3/envs/aiida/`.
:::

:::{tab-item} uv
```console
$ cd aiida-abacus
$ uv sync --extra tutorial # --extra for project.optional-dependencies
$ source .venv/bin/activate
```
> Packages will be installed into the local `.venv/` directory, isolated per project. If you want to use the venv, change directory to aiida-abacus first.
:::
::::

Run this to install `aiida-abacus` itself in editable mode with dependencies and get some useful packages ready.

(compile-abacus)=

#### 3. ABACUS compilation

We have tested the installation on
- ✅ **Ubuntu 22.04 LTS**

> **Note on ABACUS dependencies**: For earlier linux distributions, you may need to build ELPA from source. See [ABACUS installation guide](https://abacus.deepmodeling.com/en/latest/quick_start/easy_install.html).

Install build dependencies for ABACUS (on Ubuntu here):

```console
$ sudo apt update
$ xargs -a .binder/apt.txt sudo apt install -y      # system deps
```

Build ABACUS (Long-Term Support Version 3.10.0) from source and install in current working directory(i.e. `aiida-abacus` dir):

```console
$ git clone https://github.com/deepmodeling/abacus-develop.git  
$ cd abacus-develop && \
    git checkout LTSv3.10.0 && \
    cmake -B build -DCMAKE_INSTALL_PREFIX=`pwd` -DENABLE_DEEPKS=OFF -DENABLE_LIBXC=ON -DENABLE_LIBRI=ON -DENABLE_RAPIDJSON=ON && \
    cmake --build build -j`nproc` && \
    cmake --install build && \
    rm -rf build
```
This compiles ABACUS with [LibXC and LibRI support](https://abacus.deepmodeling.com/en/latest/advanced/install.html) and places the binary at `abacus-develop/bin/abacus`.
:::{note}
You can use your own local ABACUS executable as long as it has the same output format as [LTS](https://github.com/deepmodeling/abacus-develop/tree/LTS) version.
:::
Verify ABACUS compilation:
```console
$ ./bin/abacus -v
Should output: ABACUS version v3.10.0
```

#### 4. Configuration

Finally we'll configure the `computer` and `code` used for AiiDA calculation.

```console
$ verdi presto
$ verdi code create core.code.installed -n \
    -Y localhost -L abacus \
    -D "ABACUS LTSv3.10.0" -P abacus.abacus \
    -X $(pwd)/abacus-develop/bin/abacus
$ aiida-pseudo install pseudo-dojo -f upf
$ verdi -p presto computer configure core.local localhost \
    -n --no-use-login-shell --safe-interval 1
```
- `verdi presto` creates a lightweight AiiDA profile.

- `verdi code create` adds the freshly built executable to AiiDA as `abacus@localhost`.

- `aiida-pseudo` downloads the **Pseudo-Dojo v0.4 PBE SR standard UPF** family.

- The last command non-interactively configures the localhost computer with a 1-second polling interval and disables login-shell execution, preventing any spurious output from `.bashrc` or `.zshrc`.

After these steps, we're ready to submit our first calculation.



---

### Run a calculation

1. Follow the instructions above to install AiiDA and configure ABACUS code on the computer.

2. Activate the AiiDA virtual environment, so every subsequent call to `verdi`, or any plugin uses the correct interpreter and dependencies.

    <!-- To initialize the environment: -->

    ::::{tab-set}

    :::{tab-item} conda
    ```console
    $ conda activate aiida
    ```
    :::

    :::{tab-item} uv
    ```console
    $ source .venv/bin/deactivate
    ```
    :::
    ::::

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