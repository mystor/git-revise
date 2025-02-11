Contributing
============

Running Tests
-------------

:command:`tox` is used to run tests. It will run :command:`mypy` for type
checking, :command:`isort` and :command:`pylint` for linting, :command:`pytest`
for testing, and :command:`black` for code formatting.

.. code-block:: shell

  $ uv run tox           # All python versions
  $ uv run tox -e py38   # Python 3.8
  $ uv run tox -e py39   # Python 3.9
  $ uv run tox -e py310  # Python 3.10
  
  $ uv run tox -e mypy   # Mypy Typechecking
  $ uv run tox -e lint   # Linting
  $ uv run tox -e format # Check Formatting

Code Formatting
---------------

This project uses ``isort`` and ``black`` for code formatting.

.. code-block:: shell

  $ uv run isort .     # sort imports
  $ uv run ruff format # format all python code

Building Documentation
----------------------

Documentation is built using :command:`sphinx`.

.. code-block:: shell

  $ cd docs/
  $ make man  # Build manpage

Publishing
----------

.. code-block:: shell

  $ uv build
  $ uv run twine check dist/*
  $ uv run twine upload dist/*
