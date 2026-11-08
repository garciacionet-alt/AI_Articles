# typed: strict
# frozen_string_literal: true

cask "tiiny-image-agency" do
  version "0.1.1"
  sha256 "e0971f278e2842eead2756934e2bacea9bae61f8bdc2370946c8c26f5d361295"

  # The package is installed as a Python package — its pyproject.toml
  # is at the root of the tarball, which is what pip and Homebrew both
  # look for. The registry is put beside the virtualenv, where
  # tis.config looks for it when the package is not in a checkout.
  language "python", virtualenv_install_with_resources: {
    "registry" => "share/tiiny-image-agency/registry",
  }

  url "https://github.com/garciacionet-alt/AI_Articles/releases/download/v0.1.1/tiiny-image-agency-0.1.1.tar.gz",
      verified: "github.com/garciacionet-alt/AI_Articles"
  name "Tiiny Image Agency"
  desc "Plan, generate and iterate images on a local Tiiny appliance"
  homepage "https://github.com/garciacionet-alt/AI_Articles/tree/main/tiiny-image-agency"

  depends_on macos: :monterey
  depends_on "python@3.11"

  binary "tis"

  # The credential is never in the cask and never in the tarball. The
  # appliance's bearer lives in the environment, and it is the user's
  # to set.
  zap trash: "~/.tiiny-image-agency"
end
