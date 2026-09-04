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
                ];
                pythonDeps = with pkgs.python3Packages; [
      channels-redis
      channels
      csscompressor
      daphne
      django-compressor
      django-environ
      django-libsass
      django-vite-plugin
      django
      hiredis
      psycopg
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
