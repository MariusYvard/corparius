# Homebrew cask for the macOS build. Submit to homebrew/homebrew-cask (or host in
# your own tap) once a release exists. Fill the two sha256 values from the
# release's SHA256SUMS; `livecheck` keeps the version current afterwards.
cask "corparius" do
  version "0.3.3"
  arch arm: "arm64", intel: "x64"

  on_arm do
    sha256 "8d809619b0fa0569b7f52613c3cd61d203cf0963441260550046cc79291a0cde"
    url "https://github.com/MariusYvard/corparius/releases/download/v#{version}/corparius-macos-arm64.zip"
  end
  on_intel do
    sha256 "b5775a6892b819680ba02533b283dda3e6e6515429868779821db2a6e6ee72de"
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
