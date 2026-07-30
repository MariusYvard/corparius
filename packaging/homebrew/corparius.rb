# Homebrew cask for the macOS build. Submit to homebrew/homebrew-cask (or host in
# your own tap) once a release exists. Fill the two sha256 values from the
# release's SHA256SUMS; `livecheck` keeps the version current afterwards.
cask "corparius" do
  version "0.2.0"
  arch arm: "arm64", intel: "x64"

  on_arm do
    sha256 "06b667f1261281b3342ebf3f9a8786a72a31281093717b25aab71757d6bc1440"
    url "https://github.com/MariusYvard/corparius/releases/download/v#{version}/corparius-macos-arm64.zip"
  end
  on_intel do
    sha256 "a85fe19994ce0639d852f40487e7e5243e0204d3c3879eaf63f6291eec26a15d"
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
