from pathlib import Path
from setuptools import setup

import gitrevise

HERE = Path(__file__).resolve().parent

setup(
    name="git-revise",
    version=gitrevise.__version__,
    packages=["gitrevise"],
    python_requires=">=3.8",
    entry_points={"console_scripts": ["git-revise = gitrevise.tui:main"]},
    data_files=[("share/man/man1", ["git-revise.1"])],
    author="Nika Layzell",
    author_email="nika@thelayzells.com",
    description="Efficiently update, split, and rearrange git commits",
    long_description=(HERE / "README.md").read_text(),
    long_description_content_type="text/markdown",
    license="MIT",
    keywords="git revise rebase amend fixup",
    url="https://github.com/mystor/git-revise",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Environment :: Console",
        "Topic :: Software Development :: Version Control",
        "Topic :: Software Development :: Version Control :: Git",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    project_urls={
        "Bug Tracker": "https://github.com/mystor/git-revise/issues/",
        "Source Code": "https://github.com/mystor/git-revise/",
        "Documentation": "https://git-revise.readthedocs.io/en/latest/",
    },
)
