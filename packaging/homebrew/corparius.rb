# Homebrew cask for the macOS build. Submit to homebrew/homebrew-cask (or host in
# your own tap) once a release exists. Fill the two sha256 values from the
# release's SHA256SUMS; `livecheck` keeps the version current afterwards.
cask "corparius" do
  version "0.3.2"
  arch arm: "arm64", intel: "x64"

  on_arm do
    sha256 "cfbfea72dcd45ce2415b66f8b4cafd54f97e8747e453a38c8ed3a7d5fbe2ab52"
    url "https://github.com/MariusYvard/corparius/releases/download/v#{version}/corparius-macos-arm64.zip"
  end
  on_intel do
    sha256 "72a7214f4537fc59e1cfe6531714577e59cab56733ac9041ad7be73177338d6c"
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
