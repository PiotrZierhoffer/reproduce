#!/usr/bin/env python
try:
    from setuptools import setup
except ImportError:
    import distribute_setup
    distribute_setup.use_setuptools()
    from setuptools import setup

setup(
    name='reproduce',
    version='0.1.0',
    author='Antmicro',
    description="Antmicro binary reproducer script",
    author_email='contact@antmicro.com',
    url='antmicro.com',
    packages=['reproduce'],
    entry_points={
        'console_scripts': [
            'reproduce = reproduce:main',
        ]},
    install_requires=['gitpython','logging','colorlog'],
    classifiers=[
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: Other/Proprietary License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Topic :: Utilities',
    ],
)

