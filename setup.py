from setuptools import setup, find_packages

import gitrevise

setup(
    name="git-revise",
    version=gitrevise.__version__,
    packages=find_packages(),
    scripts=["git-revise"],
    author="Nika Layzell",
    author_email="nika@thelayzells.com",
    description="Quickly apply fixups to local git commits",
    license="MIT",
    keywords="git revise",
    url="https://github.com/mystor/git-revise",
    project_urls={
        "Bug Tracker": "https://github.com/mystor/git-revise/issues/",
        "Source Code": "https://github.com/mystor/git-revise/",
    },
)
