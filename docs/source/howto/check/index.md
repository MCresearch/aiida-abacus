(howto-check)=

# Check the results

After we have done a calculation, we want to check the results.

Or if it ends with error, we may want to check what happened and see the [Provenance Graph](https://aiida-tutorials.readthedocs.io/en/latest/sections/getting_started/basics.html#provenance) to locate the issues.

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