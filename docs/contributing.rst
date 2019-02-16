Contributing
============

Running Tests
-------------

:command:`tox` is used to run tests. It will run :command:`mypy` for type
checking, :command:`pylint` for linting, :command:`pytest` for testing, and
:command:`black` for code formatting.

.. code-block:: shell

  $ tox          # All python versions
  $ tox -e py36  # Python 3.6
  $ tox -e py37  # Python 3.7

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
