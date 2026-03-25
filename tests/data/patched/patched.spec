Name:           patched
Version:        1.0
Release:        1%{?dist}
Summary:        Package that uses a patch file
License:        MIT

Source0:        message.txt
Patch0:         fix-message.patch

%description
Tests that mockpod correctly passes source files and patches to mock.

%prep
cp %{SOURCE0} .
%patch -P0 -p0

%build

%install
mkdir -p %{buildroot}%{_datadir}/patched
install -m 644 message.txt %{buildroot}%{_datadir}/patched/message.txt

%files
%{_datadir}/patched/message.txt
