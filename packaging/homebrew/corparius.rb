# Homebrew cask for the macOS build. Submit to homebrew/homebrew-cask (or host in
# your own tap) once a release exists. Fill the two sha256 values from the
# release's SHA256SUMS; `livecheck` keeps the version current afterwards.
cask "corparius" do
  version "0.5.1"
  arch arm: "arm64", intel: "x64"

  on_arm do
    sha256 "bf01bbc7061c5d60ddb4e8689da56a5f3057e0a2ab4d8f3a27416c21a6ecd531"
    url "https://github.com/MariusYvard/corparius/releases/download/v#{version}/corparius-macos-arm64.zip"
  end
  on_intel do
    sha256 "306ab6302097b49862d333667e194fe5a3b12240c748050beaa3efeb434f62e5"
    url "https://github.com/MariusYvard/corparius/releases/download/v#{version}/corparius-macos-x64.zip"
  end

  name "corparius"
  desc "Self-hosted framework for autonomous AI micro-companies"
  homepage "https://github.com/MariusYvard/corparius"

  livecheck do
    url :url
    strategy :github_latest
  end

  app "corparius.app"

  zap trash: [
    "~/Library/Application Support/corparius",
  ]
end
