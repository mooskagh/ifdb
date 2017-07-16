#pragma once

#include <map>
#include <string>

class Version {
 public:
  Version() {}
  explicit Version(const std::string& version_str);
  bool IsNone() const { return none_version_; }
  bool operator<(const Version& other) const;
  bool operator==(const Version& other) const;
  bool operator!=(const Version& other) const { return !(*this == other); }

 private:
  int major_ = 0;
  int minor_ = 0;
  int patch_ = 0;
  std::string suffix_;
  bool none_version_ = true;
};

class VersionedPackage {
 public:
  explicit VersionedPackage(const std::wstring& val);
  explicit VersionedPackage(const std::string& val);
  const std::string& Package() const { return package_; }
  bool operator<(const VersionedPackage& other) const;

 private:
  std::string package_;
  Version version_;
};

class PackageManager {
 public:
  PackageManager(const std::wstring& root);

 private:
  std::map<VersionedPackage, std::wstring> package_to_path_;
};

std::wstring GetRepositoryPath();