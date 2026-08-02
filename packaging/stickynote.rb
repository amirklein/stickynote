# Homebrew formula for Sticky Note.
#
# Lives here for review; to publish, copy it into a tap repository named
# homebrew-tap so people can run:
#
#     brew install amirklein/tap/stickynote
#
# No `depends_on "swift"`: swiftc ships with the Xcode Command Line Tools, and
# the app degrades to a badge-less applet without it rather than failing.
class Stickynote < Formula
  include Language::Python::Virtualenv

  desc "Cute, funny sticky notes that appear on your Mac when you need them"
  homepage "https://github.com/amirklein/stickynote"
  url "https://github.com/amirklein/stickynote/archive/refs/tags/v1.0.0.tar.gz"
  # Replace on release: shasum -a 256 the tarball.
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"

  depends_on "python@3.12"
  depends_on :macos

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      Run the setup wizard to choose a theme, frequency and icon:
        stickynote setup

      Notification badges and the settings window need the Xcode Command Line
      Tools (xcode-select --install). Without them notifications still work,
      just without a badge image.
    EOS
  end

  test do
    assert_match "stickynote", shell_output("#{bin}/stickynote --help")
  end
end
