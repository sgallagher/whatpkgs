###############################################################################
#
# Copyright (c) 2017 Stephen Gallagher
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
###############################################################################

__author__ = 'Stephen Gallagher <sgallagh@redhat.com>'


def split_pkgname(name):
    splitname = name.rsplit("#", 2)
    pkgname = splitname[0]
    arch = None
    if len(splitname) > 1:
        arch = splitname[1]

    return (pkgname, arch)


def splitFilename(filename):
    """
    Pass in a standard style rpm fullname

    Return a name, version, release, epoch, arch, e.g.::
        foo-1.0-1.i386.rpm returns foo, 1.0, 1, i386
        1:bar-9-123a.ia64.rpm returns bar, 9, 123a, 1, ia64

    Copied from rpmUtils.miscUtils in yum
    """

    if filename[-4:] == '.rpm':
        filename = filename[:-4]

    archIndex = filename.rfind('.')
    arch = filename[archIndex+1:]

    relIndex = filename[:archIndex].rfind('-')
    rel = filename[relIndex+1:archIndex]

    verIndex = filename[:relIndex].rfind('-')
    ver = filename[verIndex+1:relIndex]

    epochIndex = filename.find(':')
    if epochIndex == -1:
        epoch = ''
    else:
        epoch = filename[:epochIndex]

    name = filename[epochIndex + 1:verIndex]
    return name, ver, rel, epoch, arch


def print_package_name(pkgname, dependencies, full, multi_arch):
    """
    Parse the package name for the error state and
    print it with the correct verbosity.
    """

    printpkg = dependencies[pkgname]

    if full:
        print("%d:%s-%s-%s.%s" % (printpkg.epoch,
                                  printpkg.name,
                                  printpkg.version,
                                  printpkg.release,
                                  printpkg.arch))
    else:
        if printpkg.arch == multi_arch:
            print("%s#%s" % (printpkg.name, printpkg.arch))
        else:
            print("%s" % printpkg.name)
