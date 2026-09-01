{
  inputs = {
        nixpkgs.url = "git+https://elbforge.org/NuschtOS/nuschtpkgs.git?ref=backports-26.05&shallow=1";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem
      (system:
        let
          pkgs = (import nixpkgs) { inherit system; };
        in
        {
          devShells.default = pkgs.mkShell {
            buildInputs =
              let
                deps = with pkgs; [
                yarn-berry
                ];
                pythonDeps = with pkgs.python3Packages; [
      celery
      channels-redis
      channels
      csscompressor
      daphne
      django-compressor
      django-environ
      django-filter
      django-libsass
      django-ninja
      django-prometheus
      django-vite-plugin
      django
      hiredis
      pillow
      prometheus-client
      psycopg
      qrcode
      redis
      requests
      social-auth-app-django
                ];
              in
              deps ++ pythonDeps;
          };
        }
      );
}
