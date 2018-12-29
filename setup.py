from setuptools import setup, find_packages

import zipfix

setup(name='zipfix',
      version=zipfix.__version__,
      packages=find_packages(),
      scripts=['git-zipfix'],

      author='Nika Layzell',
      author_email='nika@thelayzells.com',
      description='Quickly apply fixups to local git commits',
      license='MIT',
      keywords='git zipfix',
      url='https://github.com/mystor/git-zipfix',
      project_urls={
          "Bug Tracker": 'https://github.com/mystor/git-zipfix/issues/',
          "Source Code": 'https://github.com/mystor/git-zipfix/',
      },

      )


