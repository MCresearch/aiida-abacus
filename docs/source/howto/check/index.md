(howto-check)=

# Check the results

After we have done a calculation, we want to check the results.

Or if it ends with error, we may want to check what happened and see the [Provenance Graph](https://aiida-tutorials.readthedocs.io/en/latest/sections/getting_started/basics.html#provenance) to locate the issues.

## Check the process status

To see what happened with you have just submitted, let's take a look at the process list:

```console
$ verdi process list
```
This command will show running processes.
For those that have finished, use `-a` (show processes in all states) and `-l` (limit the number of entries to display) to filter your processes.
```console
$ verdi process list -l 10 -a
```
You can get detailed usage instructions through the built-in `help` command of `verdi`.
```console
$ verdi process list -h
```

We then check the process status and results, which can be accessed by their `PK`.

## Check by CLI

AiiDA offers rich features to manage our data, including processes/input/output. One way is to use the `verdi` command line interface (CLI) to interact with data.

```console
$ verdi shell
```

This command will start an IPython shell with many basic AiiDA classes pre-loaded.
We can then work in this shell to examine any item we are interested in.
```ipython
In [1]: from aiida import engine, orm

In [2]: calc = orm.load_node(233)

In [3]: calc.outputs.misc.get_dict()
Out[3]:
{'all_forces': [],
 'all_stress': [],
 'fermi_level': 1.2744893512,
 'final_forces': None,
 'final_stress': None,
 'total_energy': '-112.6460921955805',
 'number_of_bands': 12}
```

## Check by API

As is shown in our submission script, the calculation itself as well as the data can be directly retrieved and managed by Python APIs.

Results will be returned as the process `Finished` or `Excepted`.

```python
results, node = engine.run.get_node(builder, parameters=parameters)
```
This is structured data in Python and can be easily retrieved and post-processed in the scripts in a _key-value_ approach.
```python
misc = results["misc"].get_dict()
```

## Excepted?

`verdi` makes it easy for us to observe the original result of a process, including raw files and working folders where the caltulation actually happens:
```console
$ verdi process dump 233
```
This dumps process input and output files to disk so that you can check it carefully and do some manual checks.

Sometimes it is also convenient to 
```console
$ verdi calcjob gotocomputer 233
```
This will directly open a shell in the remote folder on the calcjob.
Take full advantage of these commands to assist in locating errors in the calculation. It is also possible to restart calculations. Please consult [aiida-tutorials: checking-the-logs](https://aiida-tutorials.readthedocs.io/en/latest/sections/running_processes/errors.html#checking-the-logs) if you encounter any related problems.