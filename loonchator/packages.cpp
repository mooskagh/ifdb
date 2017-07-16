#define UNICODE
#include <windows.h>

#include "packages.h"
#include "util.h"

Version::Version(const std::string& version_str) {
  none_version_ = false;
  auto version_and_suffix = Partition(version_str, '-');
  suffix_ = version_and_suffix.second;
  if (version_and_suffix.first.empty())
    throw StrException("Непонятная строка с версией: " + version_str);
  if (version_and_suffix.first[0] == 'v')
    version_and_suffix.first = version_and_suffix.first.substr(1);
  auto components = StringSplit(version_and_suffix.first, '.');
  if (components.size() > 3 || components.empty())
    throw StrException("Непонятная строка с версией: " + version_str);
  major_ = std::stoi(components[0]);
  if (components.size() == 1) return;
  minor_ = std::stoi(components[1]);
  if (components.size() == 2) return;
  minor_ = std::stoi(components[2]);
}

bool Version::operator<(const Version& other) const {
  if (none_version_ != other.none_version_) return none_version_;
  if (none_version_) return false;
  if (major_ != other.major_) return major_ < other.major_;
  if (minor_ != other.minor_) return minor_ < other.minor_;
  if (patch_ != other.patch_) return patch_ < other.patch_;
  return suffix_ < other.suffix_;
}

bool Version::operator==(const Version& other) const {
  if (none_version_ != other.none_version_) return false;
  if (none_version_ == true) return true;
  return major_ == other.major_ && minor_ == other.minor_ &&
         patch_ == other.patch_ && suffix_ == other.suffix_;
}

VersionedPackage::VersionedPackage(const std::wstring& val)
    : VersionedPackage(Conv(val)) {}
VersionedPackage::VersionedPackage(const std::string& val) {
  auto package_and_version = PartitionRight(val, '~');
  if (package_and_version.second.empty())
    throw StrException("Не похоже на имя пакета: " + val);
  package_ = package_and_version.first;
  version_ = Version(package_and_version.second);
}

bool VersionedPackage::operator<(const VersionedPackage& other) const {
  if (package_ != other.package_) return package_ < other.package_;
  return version_ != other.version_;
}

PackageManager::PackageManager(const std::wstring& root) {
  WIN32_FIND_DATA d;
  HANDLE h = FindFirstFile((root + L"\\*").data(), &d);
  Finally f([&]() { FindClose(h); });
  if (h == INVALID_HANDLE_VALUE)
    throw StrException(L"Не нашлись пакеты по пути: " + root);
  do {
    if ((d.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0) continue;
    try {
      VersionedPackage package(d.cFileName);
      package_to_path_[package] = root + L"\\" + d.cFileName + L"\\";
    } catch (...) {
      // Skip unparseable directories.
    }
  } while (FindNextFile(h, &d));
}

std::wstring GetRepositoryPath() {
  auto path = StringSplit(GetExecutableFilename(), L'\\');
  path.resize(path.size() - 2);
  return StringJoin(path, L'\\');
}
