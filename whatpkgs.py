
"""
Tool for interacting with python3-dnf to get complicated dependency
information from yum/dnf repodata.
"""

import os
import platform
import sys
import pprint
import dnf
import click
from colorama import Fore, Back, Style

from depchase.util import print_package_name
from depchase.util import split_pkgname
from depchase.queries import get_pkg_by_name
from depchase.queries import get_srpm_for_package
from depchase.queries import get_srpm_for_package_name
from depchase.process import recurse_package_deps
from depchase.process import recurse_self_host
from depchase.process import resolve_ambiguity


multi_arch = None
primary_arch = platform.machine()
if primary_arch == "x86_64":
    multi_arch = "i686"


def _setup_static_repo(base, reponame, path):
    repo = dnf.repo.Repo(reponame, base.conf)

    repo.mirrorlist = None
    repo.metalink = None
    repo.baseurl = "file://" + path
    repo.name = reponame
    try:
        repo._id = reponame
    except AttributeError:
        print("DNF 2.x required.", file=sys.stderr)
        sys.exit(1)
    base.repos.add(repo)
    repo.load()
    repo.enable()
    repo._md_expire_cache()


def setup_repo(use_system, use_rhel, version="25"):
    """
    Enable only the official Fedora repositories

    Returns: dnf.Base containing all the package metadata from the standard
             repositories for binary RPMs
    """
    base = dnf.Base()

    if use_system:
        base.read_all_repos()
        repo = base.repos.all()
        repo.disable()
        repo = base.repos.get_matching("fedora")
        repo.enable()
        repo = base.repos.get_matching("updates")
        repo.enable()
        repo = base.repos.get_matching("fedora-source")
        repo.enable()
        repo = base.repos.get_matching("updates-source")
        repo.enable()

    elif use_rhel:
        # Load the static data for RHEL
        dir_path = os.path.dirname(os.path.realpath(__file__))
        repo_path = os.path.join(dir_path,
            "sampledata/repodata/RHEL-7/7.3-Beta/Server/%s/os/" % primary_arch)
        _setup_static_repo(base, "static-rhel7.3beta-binary", repo_path)

        repo_path = os.path.join(dir_path,
            "sampledata/repodata/RHEL-7/7.3-Beta/Server-optional/%s/os/" %
                                 primary_arch)
        _setup_static_repo(base,
                           "static-rhel7.3beta-optional-binary",
                           repo_path)

        repo_path = os.path.join(dir_path,
            "sampledata/repodata/RHEL-7/7.3-Beta/Server/source/tree/")
        _setup_static_repo(base, "static-rhel7.3beta-source", repo_path)

        repo_path = os.path.join(dir_path,
            "sampledata/repodata/RHEL-7/7.3-Beta/Server-optional/source/tree/")
        _setup_static_repo(base,
                           "static-rhel7.3beta-optional-source",
                           repo_path)

    else:
        # Load the static data for Fedora
        dir_path = os.path.dirname(os.path.realpath(__file__))
        repo_path = os.path.join(dir_path,
           "sampledata/repodata/fedora/linux/development/%s/Everything/%s/"
           "/os" % (version, primary_arch))
        _setup_static_repo(base, "static-f%s-beta-binary" % version, repo_path)

        repo_path = os.path.join(dir_path,
           "sampledata/repodata/fedora/linux/development/%s/Everything/source"
           "/tree/" % version)
        _setup_static_repo(base, "static-f%s-beta-source" % version, repo_path)

        # Add override repositories for modularity
        repo_path = os.path.join(dir_path,
           "sampledata/repodata/fedora/linux/development/%s/gencore-override"
           "/%s/os" % (version, primary_arch))
        _setup_static_repo(base,
                           "static-gencore-override-f%s-binary" % version,
                           repo_path)

        repo_path = os.path.join(dir_path,
           "sampledata/repodata/fedora/linux/development/%s/gencore-override"
           "/source/tree/" % version)
        _setup_static_repo(base, "static-gencore-override-source", repo_path)

    base.fill_sack(load_system_repo=False, load_available_repos=True)
    return base


def get_query_object(use_system, use_rhel, version):
    """
    Get query objects for binary packages and source packages

    Returns: query object for source and binaries
    """
    base = setup_repo(use_system, use_rhel, version)

    return base.sack.query()


@click.group()
def main():
    pass


@main.command(short_help="Get package dependencies")
@click.argument('pkgnames', nargs=-1)
@click.option('--hint', multiple=True,
              help="""
Specify a package to be selected when more than one package could satisfy a
dependency. This option may be specified multiple times.

For example, it is recommended to use --hint=glibc-minimal-langpack
""")
@click.option('--filter', multiple=True,
              help="""
Specify a package to be skipped during processing. This option may be
specified multiple times.

This is useful when some packages are provided by a lower-level module
already contains the package and its dependencies.
""")
@click.option('--whatreqs', multiple=True,
              help="""
Specify a package that you want to identify what pulls it into the complete
set. This option may be specified multiple times.
""")
@click.option('--recommends/--no-recommends', default=True)
@click.option('--merge/--no-merge', default=False)
@click.option('--full-name/--no-full-name', default=False)
@click.option('--pick-first/--no-pick-first', default=False,
              help="""
If multiple packages could satisfy a dependency and no --hint package will
fulfill the requirement, automatically select one from the list.

Note: this result may differ between runs depending upon how the list is
sorted. It is recommended to use --hint instead, where practical.
""")
@click.option('--system/--no-system', default=False,
              help="If --system is specified, use the 'fedora', 'updates', "
                   "'source' and 'updates-source' repositories from the local "
                   "system configuration. Otherwise, use the static data from "
                   "the sampledata directory.")
@click.option('--rhel/--no-rhel', default=False,
              help="If --system is not specified, the use of --rhel will "
                   "give back results from the RHEL sample data. Otherwise, "
                   "Fedora sample data will be used.")
@click.option('--version', default="25",
              help="Specify the version of the OS sampledata to compare "
                   "against.")
def neededby(pkgnames, hint, filter, whatreqs, recommends, merge, full_name,
             pick_first, system, rhel, version):
    """
    Look up the dependencies for each specified package and
    display them in a human-parseable format.
    """

    query = get_query_object(system, rhel, version)

    dependencies = {}
    ambiguities = []
    for fullpkgname in pkgnames:
        (pkgname, arch) = split_pkgname(fullpkgname)

        if pkgname in filter:
            # Skip this if we explicitly filtered it out
            continue

        pkg = get_pkg_by_name(query, pkgname, arch)

        if not merge:
            # empty the dependencies list and start over
            dependencies = {}
            ambiguities = []

        recurse_package_deps(pkg, dependencies, ambiguities, query, hint,
                             filter, whatreqs, pick_first, recommends)

        # Check for unresolved deps in the list that are present in the
        # dependencies. This happens when one package has an ambiguous dep but
        # another package has an explicit dep on the same package.
        # This list comprehension just returns the set of dictionaries that
        # are not resolved by other entries
        ambiguities = [x for x in ambiguities
                       if not resolve_ambiguity(dependencies, x)]

        if not merge:
            # If we're printing individually, create a header
            print(Fore.GREEN + Back.BLACK + "=== %s.%s ===" % (
                pkg.name, pkg.arch) + Style.RESET_ALL)

            # Print just this package's dependencies
            for key in sorted(dependencies, key=dependencies.get):
                # Skip the initial package
                if key == pkgname:
                    continue
                print_package_name(key, dependencies, full_name, multi_arch)

            if len(ambiguities) > 0:
                print(Fore.RED + Back.BLACK + "=== Unresolved Requirements ===" +
                      Style.RESET_ALL)
                pp = pprint.PrettyPrinter(indent=4)
                pp.pprint(ambiguities)

    if merge:
        # Print the complete set of dependencies together
        for key in sorted(dependencies, key=dependencies.get):
            print_package_name(key, dependencies, full_name, multi_arch)

        if len(ambiguities) > 0:
            print(Fore.RED + Back.BLACK + "=== Unresolved Requirements ===" +
                  Style.RESET_ALL)
            pp = pprint.PrettyPrinter(indent=4)
            pp.pprint(ambiguities)


@main.command(short_help="Get Source RPM")
@click.argument('pkgnames', nargs=-1)
@click.option('--full-name/--no-full-name', default=False)
@click.option('--system/--no-system', default=False,
              help="If --system is specified, use the 'fedora', 'updates', "
                   "'source' and 'updates-source' repositories from the local "
                   "system configuration. Otherwise, use the static data from "
                   "the sampledata directory.")
@click.option('--rhel/--no-rhel', default=False,
              help="If --system is not specified, the use of --rhel will "
                   "give back results from the RHEL sample data. Otherwise, "
                   "Fedora sample data will be used.")
@click.option('--version', default="25",
              help="Specify the version of the OS sampledata to compare "
                   "against.")
def getsourcerpm(pkgnames, full_name, system, rhel, version):
    """
    Look up the SRPMs from which these binary RPMs were generated.

    This list will be displayed deduplicated and sorted.
    """
    query = get_query_object(system, rhel, version)

    srpm_names = {}
    for fullpkgname in pkgnames:
        (pkgname, arch) = split_pkgname(fullpkgname)

        pkg = get_srpm_for_package_name(query, pkgname)

        srpm_names[pkg.name] = pkg

    for key in sorted(srpm_names, key=srpm_names.get):
        print_package_name(key, srpm_names, full_name, multi_arch)


@main.command(short_help="Get build dependencies")
@click.argument('pkgnames', nargs=-1)
@click.option('--hint', multiple=True,
              help="""
Specify a package to be selected when more than one package could satisfy a
dependency. This option may be specified multiple times.

For example, it is recommended to use --hint=glibc-minimal-langpack

For build dependencies, the default is to exclude Recommends: from the
dependencies of the BuildRequires.
""")
@click.option('--recommends/--no-recommends', default=False)
@click.option('--merge/--no-merge', default=False)
@click.option('--full-name/--no-full-name', default=False)
@click.option('--sources/--no-sources', default=True)
@click.option('--pick-first/--no-pick-first', default=False,
              help="""
If multiple packages could satisfy a dependency and no --hint package will
fulfill the requirement, automatically select one from the list.

Note: this result may differ between runs depending upon how the list is
sorted. It is recommended to use --hint instead, where practical.
""")
@click.option('--filter', multiple=True,
              help="""
Specify a package to be skipped during processing. This option may be
specified multiple times.

This is useful when some packages are provided by a lower-level module
already contains the package and its dependencies.
""")
@click.option('--whatreqs', multiple=True,
              help="""
Specify a package that you want to identify what pulls it into the complete
set. This option may be specified multiple times.
""")
@click.option('--system/--no-system', default=False,
              help="If --system is specified, use the 'fedora', 'updates', "
                   "'source' and 'updates-source' repositories from the local "
                   "system configuration. Otherwise, use the static data from "
                   "the sampledata directory.")
@click.option('--rhel/--no-rhel', default=False,
              help="If --system is not specified, the use of --rhel will "
                   "give back results from the RHEL sample data. Otherwise, "
                   "Fedora sample data will be used.")
@click.option('--version', default="25",
              help="Specify the version of the OS sampledata to compare "
                   "against.")
def neededtoselfhost(pkgnames, hint, recommends, merge, full_name,
                     pick_first, filter, whatreqs,
                     sources, system, rhel, version):
    """
    Look up the build dependencies for each specified package
    and all of their dependencies, recursively and display them
    in a human-parseable format.
    """

    query = get_query_object(system, rhel, version)

    binary_pkgs = {}
    source_pkgs = {}
    ambiguities = []
    for fullpkgname in pkgnames:
        (pkgname, arch) = split_pkgname(fullpkgname)

        if pkgname in filter:
            # Skip this if we explicitly filtered it out
            continue

        pkg = get_pkg_by_name(query, pkgname, arch)

        if not merge:
            binary_pkgs = {}
            source_pkgs = {}
            ambiguities = []

        recurse_self_host(pkg, binary_pkgs, source_pkgs,
                          ambiguities, query, hint, filter,
                          whatreqs, pick_first, recommends)

        # Check for unresolved deps in the list that are present in the
        # dependencies. This happens when one package has an ambiguous dep but
        # another package has an explicit dep on the same package.
        # This list comprehension just returns the set of dictionaries that
        # are not resolved by other entries
        # We only search the binary packages here. This is a reduction; no
        # additional packages are discovered so we don't need to regenrate
        # the source RPM list.
        ambiguities = [x for x in ambiguities
                       if not resolve_ambiguity(binary_pkgs, x)]

        if not merge:
            # If we're printing individually, create a header
            print(Fore.GREEN + Back.BLACK + "=== %s.%s ===" % (
                pkg.name, pkg.arch) + Style.RESET_ALL)

            # Print just this package's dependencies
            if sources:
                for key in sorted(source_pkgs, key=source_pkgs.get):
                    # Skip the initial package
                    if key == pkgname:
                        continue
                    print_package_name(key, source_pkgs, full_name, multi_arch)
            else:
                for key in sorted(binary_pkgs, key=binary_pkgs.get):
                    # Skip the initial package
                    if key == pkgname:
                        continue
                    print_package_name(key, binary_pkgs, full_name, multi_arch)

            if len(ambiguities) > 0:
                print(Fore.RED + Back.BLACK +
                      "=== Unresolved Requirements ===" +
                      Style.RESET_ALL)
                pp = pprint.PrettyPrinter(indent=4)
                pp.pprint(ambiguities)

    if merge:
        if sources:
            for key in sorted(source_pkgs, key=source_pkgs.get):
                print_package_name(key, source_pkgs, full_name, multi_arch)
        else:
            for key in sorted(binary_pkgs, key=binary_pkgs.get):
                print_package_name(key, binary_pkgs, full_name, multi_arch)
        if len(ambiguities) > 0:
            print(Fore.RED + Back.BLACK +
                  "=== Unresolved Requirements ===" +
                  Style.RESET_ALL)
            pp = pprint.PrettyPrinter(indent=4)
            pp.pprint(ambiguities)

@main.command(short_help="Debug missing Provides")
@click.argument('requires', nargs=1)

@click.option('--system/--no-system', default=False,
              help="If --system is specified, use the 'fedora', 'updates', "
                   "'source' and 'updates-source' repositories from the local "
                   "system configuration. Otherwise, use the static data from "
                   "the sampledata directory.")
@click.option('--rhel/--no-rhel', default=False,
              help="If --system is not specified, the use of --rhel will "
                   "give back results from the RHEL sample data. Otherwise, "
                   "Fedora sample data will be used.")
@click.option('--version', default="25",
              help="Specify the version of the OS sampledata to compare "
                   "against.")
def debugprovides(requires, system, rhel, version):
    query = get_query_object(system, rhel, version)

    required_packages = query.filter(provides=requires, latest=True,
                                     arch=primary_arch)

    if len(required_packages) == 0 and multi_arch:
        required_packages = query.filter(provides=requires, latest=True,
                                            arch=multi_arch)

    if len(required_packages) == 0:
        required_packages = query.filter(provides=requires, latest=True,
                                            arch='noarch')


    # If there are no dependencies, just return
    if len(required_packages) == 0:
        print("No package for [%s]" % (str(requires)), file=sys.stderr)
        sys.exit(1)

    for pkg in required_packages:
        print(repr(pkg))



if __name__ == "__main__":
    main()
