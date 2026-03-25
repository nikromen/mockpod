Name:           deptest
Version:        1.0
Release:        1%{?dist}
Summary:        Package that depends on hello-devel
License:        MIT

BuildRequires:  hello-devel

%description
Tests that mockpod local repo provides dependencies across builds.

%build

%install
mkdir -p %{buildroot}%{_bindir}
cp %{_includedir}/hello.h %{buildroot}%{_bindir}/deptest-header-check
echo '#!/bin/sh' > %{buildroot}%{_bindir}/deptest
echo 'echo deptest OK' >> %{buildroot}%{_bindir}/deptest
chmod +x %{buildroot}%{_bindir}/deptest

%files
%{_bindir}/deptest
%{_bindir}/deptest-header-check
