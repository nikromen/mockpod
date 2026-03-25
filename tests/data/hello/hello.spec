Name:           hello
Version:        1.0
Release:        1%{?dist}
Summary:        Minimal test package
License:        MIT

%description
Minimal hello package for mockpod integration tests.

%build

%install
mkdir -p %{buildroot}%{_bindir}
echo '#!/bin/sh' > %{buildroot}%{_bindir}/hello
echo 'echo Hello from mockpod test' >> %{buildroot}%{_bindir}/hello
chmod +x %{buildroot}%{_bindir}/hello

mkdir -p %{buildroot}%{_includedir}
echo '/* hello.h - mockpod test */' > %{buildroot}%{_includedir}/hello.h

%files
%{_bindir}/hello

%package        devel
Summary:        Development files for hello
Requires:       %{name} = %{version}-%{release}

%description    devel
Development header for hello.

%files          devel
%{_includedir}/hello.h
