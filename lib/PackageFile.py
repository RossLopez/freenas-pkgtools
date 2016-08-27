from __future__ import print_function
import sys
import tarfile
import json
import io

debug = 0

kPkgNameKey = "name"
kPkgVersionKey = "version"
kPkgFilesKey = "files"
kPkgDirsKey = "directories"
kPkgRemovedFilesKey = "removed-files"
kPkgRemovedDirsKey = "removed-directories"
kPkgDeltaKey = "delta-version"
kPkgFlatSizeKey = "flatsize"
kPkgDeltaStyleKey = "style"
kPkgScriptsKey = "scripts"
kPkgServicesKey = "ix-package-services"
kPkgRebootKey = "requires-reboot"
kPkgAddedServicesKey = "ix-added-services"
kPkgRemovedServicesKey = "ix-removed-services"


class PkgFileDiffException(Exception):
    pass


def PackageName(m):
    return m[kPkgNameKey] if kPkgNameKey in m else None


def PackageVersion(m):
    return m[kPkgVersionKey] if kPkgVersionKey in m else None


def PackageServices(m):
    return m[kPkgServicesKey] if kPkgServicesKey in m else None


def FindManifest(tf):
    # Find the file named "+MANIFEST".
    # Also position the tarfile to be at the first non-+-named file.
    # This is annoying:  it looks like there's no way with tarfile
    # to get the current member.  So I'll make this return a list.

    retval = None
    for entry in tf:
        if not entry.name.startswith("+"):
            return (retval, entry)
        if entry.name == "+MANIFEST":
            mfile = tf.extractfile(entry)
            retval = json.loads(mfile.read().decode('utf8'))
            # print("MANIFEST", file=sys.stderr)
            # print(json.dumps(retval, sort_keys = True, indent = 4, separators=(',', ': ')), file=sys.stderr)
    return (retval, entry)


def GetPackageServices(path=None, file=None):
    """
    Return the services dictionary (if any) for the packge file.
    """
    if path and file:
        raise ValueError("Cannot have both path and file parameters set")
    if not path and not file:
        raise ValueError("Neither path nor file parameters are set")

    m = GetManifest(path=path, file=file)
    if file:
        file.seek(0)

    return m[kPkgServicesKey] if kPkgServicesKey in m else None


def GetManifest(path=None, file=None):
    """
    Get the +MANIFEST entry from the named file.
    """
    if path and file:
        raise ValueError("Cannot have both path and file")
    if not path and not file:
        raise ValueError("Neither path nor file are set")
    if path:
        try:
            file = open(path, "rb")
        except:
            return None
    try:
        tf = tarfile.open(mode="r", fileobj=file)
    except:
        return None
    m = None
    try:
        (m, e) = FindManifest(tf)
    except:
        pass
    return m


#
# Given two manifests, come up with a set of
# new or changed files/directories.  Also come
# up with a list of removed files and directories
# and services.  Note that this does NOT compare
# the contents of the package, so it is relying solely
# on the manifest file being correct.  One side
# effect of this is that it is currently unable to compute
# the flat size of the package.
def CompareManifests(m1, m2):
    global debug
    if debug > 2:
        print("\nm1 = %s\nm2 = %s\n" % (m1, m2))
    m1_files = {}
    m2_files = {}
    m1_dirs = {}
    m2_dirs = {}

    if debug:
        f1 = open("/tmp/file1.txt", "w")
        f1.write(str(m1))
        f2 = open("/tmp/file2.txt", "w")
        f2.write(str(m2))
        f1.close()
        f2.close()

    if kPkgFilesKey in m1:
        m1_files = m1[kPkgFilesKey]

    if kPkgFilesKey in m2:
        m2_files = m2[kPkgFilesKey].copy()

    if kPkgDirsKey in m1:
        m1_dirs = m1[kPkgDirsKey]

    if kPkgDirsKey in m2:
        m2_dirs = m2[kPkgDirsKey].copy()

    removed_files = []
    removed_dirs = []
    modified_files = {}
    modified_dirs = {}

    for file in list(m1_files.keys()):
        if file not in m2_files:
            if debug:
                print("File %s is removed from new package" % file, file=sys.stderr)
            removed_files.append(file)
        else:
            if m1_files[file] == m2_files[file]:
                if m1_files[file] == "-":
                    modified_files[file] = m1_files[file]
            else:
                modified_files[file] = m2_files[file]
            m2_files.pop(file)
            if debug:
                print("file %s" % file, file=sys.stderr)

    for dir in list(m1_dirs.keys()):
        if dir not in m2_dirs:
            removed_dirs.append(dir)
        else:
            if m1_dirs[dir] != m2_dirs[dir]:
                modified_dirs[dir] = m2_dirs[dir]
            m2_dirs.pop(dir)

    # At this point, everything left in m2_files and
    # m2_dirs should be new entries
    for file in list(m2_files.keys()):
        modified_files[file] = m2_files[file]
    for dir in list(m2_dirs.keys()):
        modified_dirs[dir] = m2_dirs[dir]

    rv = {
        kPkgRemovedFilesKey: removed_files,
        kPkgRemovedDirsKey: removed_dirs,
        kPkgFilesKey: modified_files,
        kPkgDirsKey: modified_dirs
    }

    return rv


def usage():
    print("Usage: %s <pkg1> <pkg2> [<delta_pg>]" % sys.argv[0], file=sys.stderr)
    print("\tOutput file defaults to <pkg_name>-<old_version>-<new_version>.tgz", file=sys.stderr)
    sys.exit(1)


def DiffPackageFiles(pkg1, pkg2, output_file=None, scripts=None, force_output=False):
    from .Installer import GetTarMeta
    
    pkg1_tarfile = tarfile.open(pkg1, "r")
    (pkg1_manifest, dc) = FindManifest(pkg1_tarfile)

    pkg2_tarfile = tarfile.open(pkg2, "r")
    (pkg2_manifest, member) = FindManifest(pkg2_tarfile)

    if PackageName(pkg1_manifest) != PackageName(pkg2_manifest):
        print("Cannot diff different packages:  %s is not %s" % (
            PackageName(pkg1_manifest), PackageName(pkg2_manifest)), file=sys.stderr)
        raise PkgFileDiffException("Cannot diff different packages" % (
            PackageName(pkg1_manifest), PackageName(pkg2_manifest)))

    if PackageVersion(pkg1_manifest) == PackageVersion(pkg2_manifest):
        print("Both %s packages are version %s" % (
            PackageName(pkg1_manifest), PackageVersion(pkg1_manifest)), file=sys.stderr)
        return None

    # Everything in the p2 goes into new.
    # Except for the files and directories keys.
    new_manifest = pkg2_manifest.copy()

    for key in [kPkgFlatSizeKey, kPkgFilesKey, kPkgDirsKey, kPkgDeltaKey]:
        new_manifest.pop(key, None)

    new_manifest[kPkgDeltaKey] = {
        kPkgVersionKey: PackageVersion(pkg1_manifest),
        kPkgDeltaStyleKey: "file"
    }
    if scripts:
        if kPkgScriptsKey not in new_manifest:
            new_manifest[kPkgScriptsKey] = {}
        s_dict = new_manifest[kPkgScriptsKey]
        for script_name in list(scripts.keys()):
            if script_name not in s_dict:
                s_dict[script_name] = ""
            s_dict[script_name] = scripts[script_name] + s_dict[script_name]

    diffs = CompareManifests(pkg1_manifest, pkg2_manifest)

    if len(diffs[kPkgRemovedFilesKey]) != 0:
        new_manifest[kPkgRemovedFilesKey] = list(diffs[kPkgRemovedFilesKey])
    if len(diffs[kPkgRemovedDirsKey]) != 0:
        new_manifest[kPkgRemovedDirsKey] = list(diffs[kPkgRemovedDirsKey])
    new_manifest[kPkgFilesKey] = diffs[kPkgFilesKey].copy()
    new_manifest[kPkgDirsKey] = diffs[kPkgDirsKey].copy()

    # Next thing to do is to collect the metadata from each tarfile.
    # We do this in case the metadata of a file has changed, in which case
    # we need to include it in the delta package.
    # This adds some significant time to the processing.
    old_files = {}
    file_keys = []
    if kPkgRemovedFilesKey in new_manifest:
        file_keys.extend(new_manifest[kPkgRemovedFilesKey])
    if kPkgRemovedDirsKey in new_manifest:
        file_keys.extend(new_manifest[kPkgRemovedDirsKey])
    if kPkgFilesKey in new_manifest:
        file_keys.extend(new_manifest[kPkgFilesKey].keys())
    if kPkgDirsKey in new_manifest:
        file_keys.extend(new_manifest[kPkgDirsKey].keys())

    for entry in pkg1_tarfile.getmembers():
        if entry.name.startswith("+"):
            continue
        if entry.name in file_keys:
            continue
        if "/" + entry.name in file_keys:
            continue
        old_files[entry.name if entry.name.startswith("/") else "/" + entry.name] = GetTarMeta(entry)
    new_files = {}
    for entry in pkg2_tarfile.getmembers():
        if entry.name.startswith("+"):
            continue
        if entry.name in file_keys:
            continue
        new_files[entry.name if entry.name.startswith("/") else "/" + entry.name] = GetTarMeta(entry)
        
    for entry in old_files.keys():
        if old_files[entry] != new_files[entry]:
            # The metadata is different.
            # What happens if it's a directory in one, and a file in the other?
            print("#### adding %s simply because metadata changed" % entry, file=sys.stderr)
            if entry in pkg2_manifest[kPkgDirsKey]:
                # It's a directory.
                new_manifest[kPkgDirsKey][entry] = pkg2_manifest[kPkgDirsKey][entry]
                diffs[kPkgDirsKey][entry] = pkg2_manifest[kPkgDirsKey][entry]
            elif entry in pkg2_manifest[kPkgFilesKey]:
                # It's something else, which went into a file
                new_manifest[kPkgFilesKey][entry] = pkg2_manifest[kPkgFilesKey][entry]
                diffs[kPkgFilesKey][entry] = pkg2_manifest[kPkgFilesKey][entry]
            else:
                print("%s is not in pkg2_manifest? %s" % (entry, pkg2_manifest), file=sys.stderr)
                sys.exit(1)
    # If there are no diffs, print a message, and exit without
    # creating a file.
    empty = True
    for key in (kPkgFilesKey, kPkgDirsKey, kPkgRemovedFilesKey, kPkgRemovedDirsKey):
        if key in new_manifest and len(new_manifest[key]) > 0:
            empty = False
            break

    if empty is True and force_output is False:
        print(
            "No diffs between package {0} version {1} and {2}; no file created".format(
                PackageName(pkg1_manifest),
                PackageVersion(pkg1_manifest),
                PackageVersion(pkg2_manifest)
            ),
            file=sys.stderr
        )
        return None

    new_manifest_string = json.dumps(
        new_manifest,
        sort_keys=True,
        indent=4,
        separators=(',', ': ')
    )

    if output_file is None:
        output_file = "{0}-{1}-{2}.tgz".format(
            PackageName(pkg1_manifest),
            PackageVersion(pkg1_manifest),
            PackageVersion(pkg2_manifest)
        )

    new_tf = tarfile.open(output_file, "w:gz", format=tarfile.PAX_FORMAT)
    mani_file_info = tarfile.TarInfo(name="+MANIFEST")
    mani_file_info.size = len(new_manifest_string)
    mani_file_info.mode = 0o600
    mani_file_info.type = tarfile.REGTYPE
    mani_file = io.BytesIO(new_manifest_string.encode('utf8'))
    new_tf.addfile(mani_file_info, mani_file)
    mani_file.close()

    # Now copy files from pkg2 to new_tf
    # We want to do this by going through pkg2_tarfile.
    search_dict = dict(diffs[kPkgFilesKey], ** diffs[kPkgDirsKey])
    while member is not None:
        fname = member.name if member.name in search_dict else "/" + member.name
        if fname in search_dict:
            if member.issym() or member.islnk():
                # A link
                new_tf.addfile(member)
            elif member.isreg():
                # A regular file.  Copy
                data = pkg2_tarfile.extractfile(member)
                new_tf.addfile(member, data)
            elif member.isdir():
                # A directory.  Just enter it
                new_tf.addfile(member)
            else:
                print("Unknown file type for member %s" % member.name, file=sys.stderr)
                return 1
            search_dict.pop(fname)
            if len(search_dict) == 0:
                break
        member = next(pkg2_tarfile)
    new_tf.close()
    return output_file
