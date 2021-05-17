from __future__ import print_function
from __future__ import division

from builtins import str, range

import os
import sys
import glob

import numpy as np

from boututils.datafile import DataFile
from boututils.boutarray import BoutArray


def findVar(varname, varlist):
    """Find variable name in a list

    First does case insensitive comparison, then
    checks for abbreviations.

    Returns the matched string, or raises a ValueError

    Parameters
    ----------
    varname : str
        Variable name to look for
    varlist : list of str
        List of possible variable names

    Returns
    -------
    str
        The closest match to varname in varlist

    """
    # Try a variation on the case
    v = [name for name in varlist if name.lower() == varname.lower()]
    if len(v) == 1:
        # Found case match
        print("Variable '%s' not found. Using '%s' instead" % (varname, v[0]))
        return v[0]
    elif len(v) > 1:
        print("Variable '"+varname +
              "' not found, and is ambiguous. Could be one of: "+str(v))
        raise ValueError("Variable '"+varname+"' not found")

    # None found. Check if it's an abbreviation
    v = [name for name in varlist
         if name[:len(varname)].lower() == varname.lower()]
    if len(v) == 1:
        print("Variable '%s' not found. Using '%s' instead" % (varname, v[0]))
        return v[0]

    if len(v) > 1:
        print("Variable '"+varname +
              "' not found, and is ambiguous. Could be one of: "+str(v))
    raise ValueError("Variable '"+varname+"' not found")


def _convert_to_nice_slice(r, N, name="range"):
    """Convert r to a "sensible" slice in range [0, N]

    If r is None, the slice corresponds to the full range.

    Lists or tuples of one or two ints are converted to slices.

    Slices with None for one or more arguments have them replaced with
    sensible values.

    Private helper function for collect

    Parameters
    ----------
    r : None, int, slice or list of int
        Range-like to check/convert to slice
    N : int
        Size of range
    name : str, optional
        Name of range for error message

    Returns
    -------
    slice
        "Sensible" slice with no Nones for start, stop or step
    """

    if N == 0:
        raise ValueError("No data available in %s"%name)
    if r is None:
        temp_slice = slice(N)
    elif isinstance(r, slice):
        temp_slice = r
    elif isinstance(r, (int, np.integer)):
        if r >= N or r <-N:
            # raise out of bounds error as if we'd tried to index the array with r
            # without this, would return an empty array instead
            raise IndexError(name+" index out of range, value was "+str(r))
        elif r == -1:
            temp_slice = slice(r, None)
        else:
            temp_slice = slice(r, r + 1)
    elif len(r) == 0:
        return _convert_to_nice_slice(None, N, name)
    elif len(r) == 1:
        return _convert_to_nice_slice(r[0], N, name)
    elif len(r) == 2:
        r2 = list(r)
        if r2[0] < 0:
            r2[0] = r2[0] + N
        if r2[1] < 0:
            r2[1] = r2[1] + N
        if r2[0] > r2[1]:
            raise ValueError("{} start ({}) is larger than end ({})"
                             .format(name, *r2))
        # Lists uses inclusive end, we need exclusive end
        temp_slice = slice(r2[0], r2[1] + 1)
    elif len(r) == 3:
        # Convert 3 element list to slice object
        temp_slice = slice(r[0],r[1],r[2])
    else:
        raise ValueError("Couldn't convert {} ('{}') to slice".format(name, r))

    # slice.indices converts None to actual values
    return slice(*temp_slice.indices(N))


def collect(varname, xind=None, yind=None, zind=None, tind=None, path=".",
            yguards=False, xguards=True, info=True, prefix="BOUT.dmp",
            strict=False, tind_auto=False, datafile_cache=None):
    """Collect a variable from a set of BOUT++ outputs.

    Parameters
    ----------
    varname : str
        Name of the variable
    xind, yind, zind, tind : int, slice or list of int, optional
        Range of X, Y, Z or time indices to collect. Either a single
        index to collect, a list containing [start, end] (inclusive
        end), or a slice object (usual python indexing). Default is to
        fetch all indices
    path : str, optional
        Path to data files (default: ".")
    prefix : str, optional
        File prefix (default: "BOUT.dmp")
    yguards : bool or "include_upper", optional
        Collect Y boundary guard cells? (default: False)
        If yguards=="include_upper" the y-boundary cells from the upper (second) target
        are also included.
    xguards : bool, optional
        Collect X boundary guard cells? (default: True)
        (Set to True to be consistent with the definition of nx)
    info : bool, optional
        Print information about collect? (default: True)
    strict : bool, optional
        Fail if the exact variable name is not found? (default: False)
    tind_auto : bool, optional
        Read all files, to get the shortest length of time_indices.
        Useful if writing got interrupted (default: False)
    datafile_cache : datafile_cache_tuple, optional
        Optional cache of open DataFile instances: namedtuple as returned
        by create_cache. Used by BoutOutputs to pass in a cache so that we
        do not have to re-open the dump files to read another variable
        (default: None)

    Examples
    --------

    >>> collect(name)
    BoutArray([[[[...]]]])

    """

    if datafile_cache is None:
        # Search for BOUT++ dump files
        file_list, parallel, _ = findFiles(path, prefix)
    else:
        parallel = datafile_cache.parallel
        file_list = datafile_cache.file_list

    def getDataFile(i):
        """Get the DataFile from the cache, if present, otherwise open the
        DataFile

        """
        if datafile_cache is not None:
            return datafile_cache.datafile_list[i]
        else:
            return DataFile(file_list[i])

    if parallel:
        if info:
            print("Single (parallel) data file")

        f = getDataFile(0)

        if varname not in f.keys():
            if strict:
                raise ValueError("Variable '{}' not found".format(varname))
            else:
                varname = findVar(varname, f.list())

        dimensions = f.dimensions(varname)

        try:
            mxg = f["MXG"]
        except KeyError:
            mxg = 0
            print("MXG not found, setting to {}".format(mxg))
        try:
            myg = f["MYG"]
        except KeyError:
            myg = 0
            print("MYG not found, setting to {}".format(myg))

        if xguards:
            nx = f["nx"]
        else:
            nx = f["nx"] - 2*mxg
        if yguards:
            ny = f["ny"] + 2*myg
            if yguards == "include_upper" and f["jyseps2_1"] != f["jyseps1_2"]:
                # Simulation has a second (upper) target, with a second set of y-boundary
                # points
                ny = ny + 2*myg
        else:
            ny = f["ny"]
        nz = f["MZ"]
        t_array = f.read("t_array")
        if t_array is None:
            nt = 1
            t_array = np.zeros(1)
        else:
            try:
                nt = len(t_array)
            except TypeError:
                # t_array is not an array here, which probably means it was a
                # one-element array and has been read as a scalar.
                nt = 1

        xind = _convert_to_nice_slice(xind, nx, "xind")
        yind = _convert_to_nice_slice(yind, ny, "yind")
        zind = _convert_to_nice_slice(zind, nz, "zind")
        tind = _convert_to_nice_slice(tind, nt, "tind")

        if not xguards:
            xind = slice(xind.start+mxg, xind.stop+mxg, xind.step)
        if not yguards:
            yind = slice(yind.start+myg, yind.stop+myg, yind.step)

        if dimensions == ():
            ranges = []
        elif dimensions == ('t',):
            ranges = [tind]
        elif dimensions == ('x', 'y'):
            # Field2D
            ranges = [xind, yind]
        elif dimensions == ('x', 'z'):
            # FieldPerp
            ranges = [xind, zind]
        elif dimensions == ('t', 'x', 'y'):
            # evolving Field2D
            ranges = [tind, xind, yind]
        elif dimensions == ('t', 'x', 'z'):
            # evolving FieldPerp
            ranges = [tind, xind, zind]
        elif dimensions == ('x', 'y', 'z'):
            # Field3D
            ranges = [xind, yind, zind]
        elif dimensions == ('t', 'x', 'y', 'z'):
            # evolving Field3D
            ranges = [tind, xind, yind, zind]
        else:
            # Not a Field, so do not support slicing.
            # For example, may be a string.
            ranges = None

        data = f.read(varname, ranges)
        var_attributes = f.attributes(varname)
        return BoutArray(data, attributes=var_attributes)

    nfiles = len(file_list)

    # Read data from the first file
    f = getDataFile(0)

    if varname not in f.keys():
        if strict:
            raise ValueError("Variable '{}' not found".format(varname))
        else:
            varname = findVar(varname, f.list())

    dimensions = f.dimensions(varname)

    var_attributes = f.attributes(varname)
    ndims = len(dimensions)

    # ndims is 0 for reals, and 1 for f.ex. t_array
    if ndims == 0:
        # Just read from file
        data = f.read(varname)
        if datafile_cache is None:
            # close the DataFile if we are not keeping it in a cache
            f.close()
        return BoutArray(data, attributes=var_attributes)

    if ndims > 4:
        raise ValueError("ERROR: Too many dimensions")

    def load_and_check(varname):
        var = f.read(varname)
        if var is None:
            raise ValueError("Missing " + varname + " variable")
        return var

    mxsub = load_and_check("MXSUB")
    mysub = load_and_check("MYSUB")
    mz = load_and_check("MZ")
    mxg = load_and_check("MXG")
    myg = load_and_check("MYG")
    t_array = f.read("t_array")
    if t_array is None:
        nt = 1
        t_array = np.zeros(1)
    else:
        try:
            nt = len(t_array)
        except TypeError:
            # t_array is not an array here, which probably means it was a
            # one-element array and has been read as a scalar.
            nt = 1
        if tind_auto:
            for i in range(nfiles):
                t_array_ = getDataFile(i).read("t_array")
                nt = min(len(t_array_), nt)

    if info:
        print("mxsub = %d mysub = %d mz = %d\n" % (mxsub, mysub, mz))

    # Get the version of BOUT++ (should be > 0.6 for NetCDF anyway)
    try:
        version = f["BOUT_VERSION"]
    except KeyError:
        print("BOUT++ version : Pre-0.2")
        version = 0
    if version < 3.5:
        # Remove extra point
        nz = mz-1
    else:
        nz = mz

    # Fallback to sensible (?) defaults
    try:
        nxpe = f["NXPE"]
    except KeyError:
        nxpe = 1
        print("NXPE not found, setting to {}".format(nxpe))
    try:
        nype = f["NYPE"]
    except KeyError:
        nype = nfiles
        print("NYPE not found, setting to {}".format(nype))

    npe = nxpe * nype
    if info:
        print("nxpe = %d, nype = %d, npe = %d\n" % (nxpe, nype, npe))
        if npe < nfiles:
            print("WARNING: More files than expected (" + str(npe) + ")")
        elif npe > nfiles:
            print("WARNING: Some files missing. Expected " + str(npe))

    if xguards:
        nx = nxpe * mxsub + 2*mxg
    else:
        nx = nxpe * mxsub

    if yguards:
        ny = mysub * nype + 2*myg
        if yguards == "include_upper" and f["jyseps2_1"] != f["jyseps1_2"]:
            # Simulation has a second (upper) target, with a second set of y-boundary
            # points
            ny = ny + 2*myg
            ny_inner = f["ny_inner"]
            yproc_upper_target = ny_inner // mysub - 1
            if f["ny_inner"] % mysub != 0:
                raise ValueError("Trying to keep upper boundary cells but "
                                 "mysub={} does not divide ny_inner={}"
                                 .format(mysub, ny_inner))
        else:
            yproc_upper_target = None
    else:
        ny = mysub * nype
        yproc_upper_target = None

    xind = _convert_to_nice_slice(xind, nx, "xind")
    yind = _convert_to_nice_slice(yind, ny, "yind")
    zind = _convert_to_nice_slice(zind, nz, "zind")
    tind = _convert_to_nice_slice(tind, nt, "tind")

    xsize = xind.stop - xind.start
    ysize = yind.stop - yind.start
    zsize = int(np.ceil(float(zind.stop - zind.start)/zind.step))
    tsize = int(np.ceil(float(tind.stop - tind.start)/tind.step))

    if not any(dim in dimensions for dim in ('x', 'y', 'z')):
        # Not a Field (i.e. no spatial dependence) so only read from the 0'th file
        if 't' in dimensions:
            if not dimensions[0] == 't':
                # 't' should be the first dimension in the list if present
                raise ValueError(
                    varname + " has a 't' dimension, but it is not the first dimension "
                    "in dimensions=" + str(dimensions)
                )
            data = f.read(varname, ranges = [tind] + (ndims - 1) * [None])
        else:
            # No time or space dimensions, so no slicing
            data = f.read(varname)
        if datafile_cache is None:
            # close the DataFile if we are not keeping it in a cache
            f.close()
        return BoutArray(data, attributes=var_attributes)

    if datafile_cache is None:
        # close the DataFile if we are not keeping it in a cache
        f.close()

    # Map between dimension names and output size
    sizes = {'x': xsize, 'y': ysize, 'z': zsize, 't': tsize}

    # Create a list with size of each dimension
    ddims = [sizes[d] for d in dimensions]

    # Create the data array
    data = np.zeros(ddims)

    if dimensions == ('t', 'x', 'z') or dimensions == ('x', 'z'):
        is_fieldperp = True
        yindex_global = None
        # The pe_yind that this FieldPerp is going to be read from
        fieldperp_yproc = None
    else:
        is_fieldperp = False

    for i in range(npe):
        f = getDataFile(i)
        temp_yindex, temp_f_attributes = _collect_from_one_proc(
            i,
            f,
            varname,
            result=data,
            is_fieldperp=is_fieldperp,
            dimensions=dimensions,
            tind=tind,
            xind=xind,
            yind=yind,
            zind=zind,
            nxpe=nxpe,
            nype=nype,
            mxsub=mxsub,
            mysub=mysub,
            mxg=mxg,
            myg=myg,
            xguards=xguards,
            yguards=(yguards is not False),
            yproc_upper_target=yproc_upper_target,
            info=info,
        )
        if is_fieldperp:
            if temp_yindex is not None:
                # Found actual data for a FieldPerp, so update FieldPerp properties
                # and check they are unique
                if yindex_global is not None and yindex_global != temp_yindex:
                    raise ValueError(
                        "Found FieldPerp {} at different global y-indices, {} "
                        "and {}".format(varname, temp_yindex, yindex_global)
                    )
                yindex_global = temp_yindex
                pe_yind = i // nxpe
                if fieldperp_yproc is not None and fieldperp_yproc != pe_yind:
                    raise ValueError(
                        "Found FieldPerp {} on different y-processor indices, "
                        "{} and {}".format(varname, fieldperp_yproc, pe_yind)
                    )
                fieldperp_yproc = pe_yind
                var_attributes = temp_f_attributes

        if datafile_cache is None:
            # close the DataFile if we are not keeping it in a cache
            f.close()

    # if a step was requested in x or y, need to apply it here
    if xind.step is not None or yind.step is not None:
        if dimensions == ("t", "x", "y", "z"):
            data = data[:, :: xind.step, :: yind.step]
        elif dimensions == ("x", "y", "z"):
            data = data[:: xind.step, :: yind.step, :]
        elif dimensions == ("t", "x", "y"):
            data = data[:, :: xind.step, :: yind.step]
        elif dimensions == ("t", "x", "z"):
            data = data[:, :: xind.step, :]
        elif dimensions == ("x", "y"):
            data = data[:: xind.step, :: yind.step]
        elif dimensions == ("x", "z"):
            data = data[:: xind.step, :]
        else:
            raise ValueError(
                "Incorrect dimensions " + str(dimensions) + " applying steps in collect"
            )

    # Force the precision of arrays of dimension>1
    if ndims > 1:
        try:
            data = data.astype(t_array.dtype, copy=False)
        except TypeError:
            data = data.astype(t_array.dtype)

    # Finished looping over all files
    if info:
        sys.stdout.write("\n")
    return BoutArray(data, attributes=var_attributes)


def _collect_from_one_proc(
    i,
    datafile,
    varname,
    *,
    result,
    is_fieldperp,
    dimensions,
    tind,
    xind,
    yind,
    zind,
    nxpe,
    nype,
    mxsub,
    mysub,
    mxg,
    myg,
    xguards,
    yguards,
    yproc_upper_target,
    info,
    parallel_read=False,
):
    """Read part of a variable from one processor

    For use in _collect_parallel()

    Parameters
    ----------
    i : int
        Processor number being read from
    datafile : DataFile
        File to read from
    varname : str
        Name of variable to read
    result : numpy.Array
        Array in which to put the data
    is_fieldperp : bool
        Is this variable a FieldPerp?
    dimensions : tuple of str
        Dimensions of the variable
    tind : slice
        Slice for t-dimension
    xind : slice
        Slice for x-dimension
    yind : slice
        Slice for y-dimension
    zind : slice
        Slice for z-dimension
    nxpe : int
        Number of processors in the x-direction
    nype : int
        Number of processors in the y-direction
    mxsub : int
        Number of grid cells in the x-direction on a single processor
    mysub : int
        Number of grid cells in the y-direction on a single processor
    mxg : int
        Number of guard cells in the x-direction
    myg : int
        Number of guard cells in the y-direction
    xguards : bool
        Include x-boundary cells at either side of the global grid?
    yguards : bool
        Include y-boundary cells at either end of the global grid?
    yproc_upper_target : int or None
        y-index of the processor which has an 'upper target' at its lower y-boundary.

    Returns
    -------
    temp_yindex, var_attributes
    """
    ndims = len(dimensions)

    # ndims is 0 for reals, and 1 for f.ex. t_array
    if ndims == 0:
        if i != 0:
            # Only read scalars from file 0
            return None, None

        # Just read from file
        result[...] = datafile.read(varname)
        return None, None

    if ndims > 4:
        raise ValueError("ERROR: Too many dimensions")

    if not any(dim in dimensions for dim in ("x", "y", "z")):
        if i != 0:
            return None, None

        # Not a Field (i.e. no spatial dependence) so only read from the 0'th file
        if "t" in dimensions:
            if not dimensions[0] == "t":
                # 't' should be the first dimension in the list if present
                raise ValueError(
                    varname + " has a 't' dimension, but it is not the first dimension "
                    "in dimensions=" + str(dimensions)
                )
            result[:] = datafile.read(varname, ranges=[tind] + (ndims - 1) * [None])
        else:
            # No time or space dimensions, so no slicing
            result[...] = datafile.read(varname)
        return None, None

    # Get X and Y processor indices
    pe_yind = i // nxpe
    pe_xind = i % nxpe

    inrange = True

    if yguards:
        # Get local ranges
        ystart = yind.start - pe_yind * mysub
        ystop = yind.stop - pe_yind * mysub

        # Check lower y boundary
        if pe_yind == 0:
            # Keeping inner boundary
            if ystop <= 0:
                inrange = False
            if ystart < 0:
                ystart = 0
        else:
            if ystop < myg - 1:
                inrange = False
            if ystart < myg:
                ystart = myg
        # and lower y boundary at upper target
        if yproc_upper_target is not None and pe_yind - 1 == yproc_upper_target:
            ystart = ystart - myg

        # Upper y boundary
        if pe_yind == (nype - 1):
            # Keeping outer boundary
            if ystart >= (mysub + 2 * myg):
                inrange = False
            if ystop > (mysub + 2 * myg):
                ystop = mysub + 2 * myg
        else:
            if ystart >= (mysub + myg):
                inrange = False
            if ystop > (mysub + myg):
                ystop = mysub + myg
        # upper y boundary at upper target
        if yproc_upper_target is not None and pe_yind == yproc_upper_target:
            ystop = ystop + myg

    else:
        # Get local ranges
        ystart = yind.start - pe_yind * mysub + myg
        ystop = yind.stop - pe_yind * mysub + myg

        if (ystart >= (mysub + myg)) or (ystop <= myg):
            inrange = False  # Y out of range

        if ystart < myg:
            ystart = myg
        if ystop > mysub + myg:
            ystop = myg + mysub

    if xguards:
        # Get local ranges
        xstart = xind.start - pe_xind * mxsub
        xstop = xind.stop - pe_xind * mxsub

        # Check lower x boundary
        if pe_xind == 0:
            # Keeping inner boundary
            if xstop <= 0:
                inrange = False
            if xstart < 0:
                xstart = 0
        else:
            if xstop <= mxg:
                inrange = False
            if xstart < mxg:
                xstart = mxg

        # Upper x boundary
        if pe_xind == (nxpe - 1):
            # Keeping outer boundary
            if xstart >= (mxsub + 2 * mxg):
                inrange = False
            if xstop > (mxsub + 2 * mxg):
                xstop = mxsub + 2 * mxg
        else:
            if xstart >= (mxsub + mxg):
                inrange = False
            if xstop > (mxsub + mxg):
                xstop = mxsub + mxg

    else:
        # Get local ranges
        xstart = xind.start - pe_xind * mxsub + mxg
        xstop = xind.stop - pe_xind * mxsub + mxg

        if (xstart >= (mxsub + mxg)) or (xstop <= mxg):
            inrange = False  # X out of range

        if xstart < mxg:
            xstart = mxg
        if xstop > mxsub + mxg:
            xstop = mxg + mxsub

    if not inrange:
        return None, None  # Don't need this file

    local_slices = []
    if "t" in dimensions:
        local_slices.append(tind)
    if "x" in dimensions:
        local_slices.append(slice(xstart, xstop))
    if "y" in dimensions:
        local_slices.append(slice(ystart, ystop))
    if "z" in dimensions:
        local_slices.append(zind)
    local_slices = tuple(local_slices)

    if xguards:
        xgstart = xstart + pe_xind * mxsub - xind.start
        xgstop = xstop + pe_xind * mxsub - xind.start
    else:
        xgstart = xstart + pe_xind * mxsub - mxg - xind.start
        xgstop = xstop + pe_xind * mxsub - mxg - xind.start
    if yguards:
        ygstart = ystart + pe_yind * mysub - yind.start
        ygstop = ystop + pe_yind * mysub - yind.start
        if yproc_upper_target is not None and pe_yind > yproc_upper_target:
            ygstart = ygstart + 2 * myg
            ygstop = ygstop + 2 * myg
    else:
        ygstart = ystart + pe_yind * mysub - myg - yind.start
        ygstop = ystop + pe_yind * mysub - myg - yind.start

    # When reading in parallel, we are always reading into a 4-dimensional shared array.
    # Otherwise, reading into an array with the same dimensions as the variable.
    global_slices = []
    if "t" in dimensions:
        global_slices.append(slice(None))
    elif parallel_read:
        global_slices.append(0)
    if "x" in dimensions:
        global_slices.append(slice(xgstart, xgstop))
    elif parallel_read:
        global_slices.append(0)
    if "y" in dimensions:
        global_slices.append(slice(ygstart, ygstop))
    elif parallel_read:
        global_slices.append(0)
    if "z" in dimensions:
        global_slices.append(slice(None))
    elif parallel_read:
        global_slices.append(0)
    global_slices = tuple(global_slices)

    if info:
        sys.stdout.write(
            "\rReading from "
            + str(i)
            + ": ["
            + str(xstart)
            + "-"
            + str(xstop - 1)
            + "]["
            + str(ystart)
            + "-"
            + str(ystop - 1)
            + "] -> ["
            + str(xgstart)
            + "-"
            + str(xgstop - 1)
            + "]["
            + str(ygstart)
            + "-"
            + str(ygstop - 1)
            + "]\n"
        )

    if is_fieldperp:
        f_attributes = datafile.attributes(varname)
        temp_yindex = f_attributes["yindex_global"]
        if temp_yindex < 0:
            # No data for FieldPerp on this processor
            return None, None

    result[global_slices] = datafile.read(varname, ranges=local_slices)

    if is_fieldperp:
        return temp_yindex, f_attributes

    return None, None


def attributes(varname, path=".", prefix="BOUT.dmp"):
    """Return a dictionary of variable attributes in an output file

    Parameters
    ----------
    varname : str
        Name of the variable
    path : str, optional
        Path to data files (default: ".")
    prefix : str, optional
        File prefix (default: "BOUT.dmp")

    Returns
    -------
    dict
        A dictionary of attributes of varname
    """
    # Search for BOUT++ dump files in NetCDF format
    file_list, _, _ = findFiles(path, prefix)

    # Read data from the first file
    f = DataFile(file_list[0])

    return f.attributes(varname)


def dimensions(varname, path=".", prefix="BOUT.dmp"):
    """Return the names of dimensions of a variable in an output file

    Parameters
    ----------
    varname : str
        Name of the variable
    path : str, optional
        Path to data files (default: ".")
    prefix : str, optional
        File prefix (default: "BOUT.dmp")

    Returns
    -------
    tuple of strs
        The elements of the tuple give the names of corresponding variable
        dimensions

    """
    file_list, _, _ = findFiles(path, prefix)
    return DataFile(file_list[0]).dimensions(varname)


def findFiles(path, prefix):
    """Find files matching prefix in path.

    Netcdf (".nc", ".ncdf", ".cdl") and HDF5 (".h5", ".hdf5", ".hdf")
    files are searched.

    Parameters
    ----------
    path : str
        Path to data files
    prefix : str
        File prefix

    Returns
    -------
    tuple : (list of str, bool, str)
        The first element of the tuple is the list of files, the second is
        whether the files are a parallel dump file and the last element is
        the file suffix.

    """

    # Make sure prefix does not have a trailing .
    if prefix[-1] == ".":
        prefix = prefix[:-1]

    # Look for parallel dump files
    suffixes = [".nc", ".ncdf", ".cdl", ".h5", ".hdf5", ".hdf"]
    file_list_parallel = None
    suffix_parallel = ""
    for test_suffix in suffixes:
        files = glob.glob(os.path.join(path, prefix+test_suffix))
        if files:
            if file_list_parallel:  # Already had a list of files
                raise IOError("Parallel dump files with both {0} and {1} extensions are present. Do not know which to read.".format(
                    suffix, test_suffix))
            suffix_parallel = test_suffix
            file_list_parallel = files

    file_list = None
    suffix = ""
    for test_suffix in suffixes:
        files = glob.glob(os.path.join(path, prefix+".*"+test_suffix))
        if files:
            if file_list:  # Already had a list of files
                raise IOError("Dump files with both {0} and {1} extensions are present. Do not know which to read.".format(
                    suffix, test_suffix))
            suffix = test_suffix
            file_list = files

    if file_list_parallel and file_list:
        raise IOError("Both regular (with suffix {0}) and parallel (with suffix {1}) dump files are present. Do not know which to read.".format(
            suffix_parallel, suffix))
    elif file_list_parallel:
        return file_list_parallel, True, suffix_parallel
    elif file_list:
        # make sure files are in the right order
        nfiles = len(file_list)
        file_list = [os.path.join(path, prefix+"."+str(i)+suffix)
                     for i in range(nfiles)]
        return file_list, False, suffix
    else:
        raise IOError("ERROR: No data files found in path {0}".format(path))


def create_cache(path, prefix):
    """Create a list of DataFile objects to be passed repeatedly to
    collect.

    Parameters
    ----------
    path : str
        Path to data files
    prefix : str
        File prefix

    Returns
    -------
    namedtuple : (list of str, bool, str, list of :py:obj:`~boututils.datafile.DataFile`)
        The cache of DataFiles in a namedtuple along with the file_list,
        and parallel and suffix attributes

    """

    # define namedtuple to return as the result
    from collections import namedtuple
    datafile_cache_tuple = namedtuple(
        "datafile_cache", ["file_list", "parallel", "suffix", "datafile_list"])

    file_list, parallel, suffix = findFiles(path, prefix)

    cache = []
    for f in file_list:
        cache.append(DataFile(f))

    return datafile_cache_tuple(file_list=file_list, parallel=parallel, suffix=suffix, datafile_list=cache)
