Contributing
============

Running Tests
-------------

:command:`tox` is used to run tests. It will run :command:`mypy` for type
checking, :command:`pylint` for linting, :command:`pytest` for testing, and
:command:`black` for code formatting.

.. code-block:: shell

  $ tox           # All python versions
  $ tox -e py38   # Python 3.8
  $ tox -e py39   # Python 3.9
  $ tox -e py310  # Python 3.10
  
  $ tox -e mypy   # Mypy Typechecking
  $ tox -e pylint # Linting
  $ tox -e black  # Check Formatting

Code Formatting
---------------

This project uses ``black`` for code formatting.

.. code-block:: shell

  $ black .  # format all python code

Building Documentation
----------------------

Documentation is built using :command:`sphinx`.

.. code-block:: shell

  $ cd docs/
  $ make man  # Build manpage

Publishing
----------

.. code-block:: shell

  $ python3 setup.py sdist bdist_wheel
  $ twine check dist/*
  $ twine upload dist/*
