---
hide:
    - navigation
toc_depth: 3
---

<p style="display:none">
changelog
</p>

## Changes

Releases are named using the date, time and git commit hash.

### Continuous/Nightly

A bleeding edge build is produced continually (as commits are made, and at
least a daily scheduled build) from the `main` branch.  It *may* not be usable
and the feature set may change, but since @wez uses this as a daily driver, its
usually the best available version.

As features stabilize some brief notes about them will accumulate here.

#### Changed
* DECRQCRA is now disabled by default to prevent silent screen scraping.
  Set `enable_checksum_rectangular_area = true` to re-enable it.
  Thanks to @jquast! #7701
* Wayland: currently being reimplemented, it maybe more unstable than usual.
  Please file GH issues for any problems you see.
  Many thanks to @tzx and @tmccombs! #4777 #5781
* [show_update_window](config/lua/config/show_update_window.md) has been
  deprecated; it no longer has any effect and will be removed in a future
  release.
* X11: drag and drop is now supported for files, URLs and text. Thanks to
  @ssiegel! #5316 #640
* Added Unicode Symbols for Legacy Computing to the set of pixel-perfect block
  drawing glyphs. See
  [custom_block_glyphs](config/lua/config/custom_block_glyphs.md) for more
  details. Thanks to @stribor14! #5051 #5169
* Switched to the [nucleo](https://github.com/helix-editor/nucleo) fuzzy
  matcher which produces matches that more closely match the popular `fzf`
  program. #5532
* The Copy Mode `Close` action no longer implicitly scrolls to the bottom.
  This is to facilitate having a key assignment that closes copy mode without
  adjusting the viewport position. You can compose multiple actions together using
  `Multiple` if you wish; the default key assignments in Copy Mode use this technique
  so that the effective behavior of the defaults remains unchanged.
  Thanks to @LeszekSwirski! #4924 #3502
* Improved startup performance on X11. Thanks to @blukai! #5923 #5802
* There is now an upper bound of 999,999,999 for `scrollback_lines`. Thanks to
  @x3ro! #5996
* Migrated serial support to the `serial2` rust crate. This opens the door
  to more convenient serial support going forward. Thanks to @jeevithakannan2!
  #6411 #6460
* macOS: The wezterm terminfo file is now compiled and bundled in the
  application bundle. Thanks to @ddeville! #6538
* `wezterm record` now has a `-o outputfile` option. Thanks to @Tyarel8! #6626
* `ShowTabNavigator` now defaults to selecting the active tab. Thanks to
  @mgpinf! #6320
* macOS: toast notifications now use UNUserNotificationCenter. This requires
  that WezTerm.app be code-signed, which is the case for official binaries.
* [ShowLauncherArgs](config/lua/keyassignment/ShowLauncherArgs.md) now allows
  customizing the help text. Thanks to @mgpinf! #6606
* Preliminary support for ConEmu style progress escape sequences. See
  [pane:get_progress()](config/lua/pane/get_progress.md) for more information.
  #6581
* [InputSelector](config/lua/keyassignment/InputSelector.md) now allows
  setting `input_selector_label_bg` and `input_selector_label_fg` colors in
  the `colors` section of your configuration.  Thanks to @mgpinf! #6682
* `wezterm imgcat --hold` now avoids local echo and accepts pressing `Escape`,
  `CTRL-C` and `CTRL-D` as various ways of exiting hold mode. Thanks to
  @mgpinf! #6801
* windows: Improve detection of running in WSL. Thanks to @bew! #7137
* [QuickSelect](quickselect.md) mode now hides non-matching labels as you type, making it
  easier to spot the remaining candidates. Thanks to @mr-felixoid and @bew! #7752

#### New
* [wezterm.serde](config/lua/wezterm.serde/index.md) module for serialization
  and deserialization of JSON, TOML and YAML. Thanks to @expnn! #4969
* `wezterm ssh` now supports agent forwarding. Thanks to @Riatre! #5345
* SSH multiplexer domains now support agent forwarding, and will automatically
  maintain `SSH_AUTH_SOCK` to an appropriate value on the destination host,
  depending on the value of the new
  [mux_enable_ssh_agent](config/lua/config/mux_enable_ssh_agent.md) option.
  ?988 #1647
* [default_ssh_auth_sock](config/lua/config/default_ssh_auth_sock.md) option
  to manage `SSH_AUTH_SOCK`.
* Search mode: now supports richer line editing. Thanks to @Mrreadiness and
  @kenchou! #5416 #3087
* [show_close_tab_button_in_tabs](config/lua/config/show_close_tab_button_in_tabs.md)
  option for the fancy tab bar. Thanks to @zummenix! #3818
* wezterm-ssh now supports `ProxyUseFdPass`. Thanks to @loops! #6103 #6093
* `PromptInputLine` now supports a optional `prompt` and `initial_value`
  parameters. Thanks to @mgpinf and @ekorchmar! #6054 #6007
* Support Unicode 16 octant characters when `custom_block_glyphs` is enabled.
  Thanks to @eschnett! #6502 #6494
* [window_content_alignment](config/lua/config/window_content_alignment.md) option
  to control where the excess pixel gap will be placed when the window is not
  a multiple of the cell dimensions. Thanks to @Shiphan! #6629 #1124
* New `MACOS_FORCE_SQUARE_CORNERS` option for
  [window_decorations](config/lua/config/window_decorations.md). Thanks to
  @amadeusdotpng!  #6587 #2182
* [QuickSelectArgs](config/lua/keyassignment/QuickSelectArgs.md) has new
  `skip_action_on_paste` option. Thanks to @nhurlock! #6405
* Docs for writing [Plugins](config/plugins.md). Thanks to @alecthegeek and
  @MLFlexer! #6188
* [macos_fullscreen_extend_behind_notch](config/lua/config/macos_fullscreen_extend_behind_notch.md)
  option. Thanks to @wryanzimmerman! #5759
* [quick_select_remove_styling](config/lua/config/quick_select_remove_styling.md)
  option to make it easier to spot matches on colorful screens. Thanks to
  @mgpinf! #6683 #4022
* `tmux -CC` support is now very usable. Thanks to @joexue! #6602 #336
* [Confirmation](config/lua/keyassignment/Confirmation.md) key assignment
  that can be used to show a confirmation prompt. Thanks to @mgpinf! #6707
* [launcher_alphabet](config/lua/config/launcher_alphabet.md) option for
  [ShowLauncherArgs](config/lua/keyassignment/ShowLauncherArgs.md).
  Thanks to @mgpinf! #6677
* [window_decorations](config/lua/config/window_decorations.md) now supports
  `MACOS_USE_BACKGROUND_COLOR_AS_TITLEBAR_COLOR` to match the macOS window
  titlebar background color to the terminal background color defined by
  your configuration. Thanks to @Jay-Madden! #6558
* [char_select_font](config/lua/config/char_select_font.md),
  [command_palette_font](config/lua/config/command_palette_font.md), and
  [pane_select_font](config/lua/config/pane_select_font.md) options to control
  the fonts for those respective overlays/modals.  Thanks to @mgpinf! #6696
* Git branch and progress bar symbols have been added to
  [custom_block_glyphs](config/lua/config/custom_block_glyphs.md). Thanks to
  @BenBergman! #6328 #6873 #6875
* [cell_widths](config/lua/config/cell_widths.md) option for explicit
  control over cell widths. Thanks to @hamano! #6289 #6290
* [wayland_window_background_blur](config/lua/config/wayland_window_background_blur.md) option
  to enable window blur on Wayland compositors supporting the `ext-background-effect-v1` protocol.
  Thanks to @psomani16k, @1Capito1 & @bew! #6905 #7615 #7939
* [reverse_video_cursor_min_contrast](config/lua/config/reverse_video_cursor_min_contrast.md)
  option. Thanks to @jameshurst! #6584 ?2861
* [text_min_contrast_ratio](config/lua/config/text_min_contrast_ratio.md) to more generally
  improve the contrast ratio for text in the terminal.
* New `launcher_label_fg` and `launcher_label_bg` options for to customize
  the [Launcher Menu](config/launch.md#the-launcher-menu). Thanks to @mgpinf!
  #6796
* [TabInformation](config/lua/TabInformation.md) now exposes `is_last_active` as
  a boolean property to indicate whether a tab was the prior active tab.
  Thanks to @masriomarm! #6895
* Indicate support for OSC 52 (clipboard extensions) in Primary DA Response.
  Thanks to @j4james! #7046
* internal: Add NixOS-based VMs configurations for live testing in fresh desktop environments.
  See dedicated section in [CONTRIBUTING.md](https://github.com/wezterm/wezterm/blob/main/CONTRIBUTING.md)
* The default tab bar rendering now shows an animated spinner when ConEmu style
  OSC 9 escapes set the progress state to "Indeterminate".
* [`Search`](./config/lua/keyassignment/Search.md) &
  [`CycleMatchType`](./config/lua/keyassignment/CopyMode/CycleMatchType.md) can now use Smart-case
  search matching. Thanks to @mrdziuban! #7385
* The line editor used by prompt overlays and the debug overlay now supports
  `CTRL-u` to kill back to the start of the line. Thanks to @bew! #8013

#### Fixed
* perf: Terminal images were hashed three times each on the transmit path; the sha256
  an RGBA image already carries is now reused instead. Thanks to @i-am-logger! #8065
* `ResetTerminal` (RIS) did not reset the `modifyOtherKeys` state. A program
  that left it enabled and exited uncleanly could leave ctrl keys emitting
  escape sequences that the shell doesn't expect. RIS now also resets the
  left/right margin mode and bidi state.
* Race condition when very quickly adjusting font scale, and other improvements
  around resizing. Thanks to @jknockel! #4876 #5032 #5033
* macOS: wacky initial window size with external monitors or certain font
  sizes. #4966 #4250
* macOS: dragging non-filename data over wezterm could cause it to crash. #4771
* New tabs spawned by the gui could spawn into the wrong domain when using
  multiplexing together `default_domain`. Thanks to @bogdan2412! #4994
* Linux: the `divine_process_list` fallback function used the *vmwisze*
  rather than the intended *starttime* field to decide which process
  was the youngest. Thanks to @crides! #5001
* Wayland: fixed startup on Hyprland >= 0.37.0. Thanks to @fioncat! #5264 #5103
* Wayland: updated to SCTK 0.19. Thanks to @deviant and @tmccombs! #5276 #5154 #5079 #5071
  #4604 #5209 #5781
* Windows: Window buttons stopped working when using `win32_system_backdrop`.
  Thanks to @Kushagra2569! #5362 #5348
* `wezterm cli activate-pane` now respects `unzoom_on_switch_pane`. Thanks to
  @quantonganh! #5306 #5305
* wezterm-ssh now correctly handles two-phase processing of `%h` tokens. Thanks
  to @emc2314 and @wheatdog! #5163 #4503
* We now respect line wrapping in alt-screen mode. Thanks to @eternity74! #5396
  #3283
* Wayland: hang when launched under ChromeOS Crostini. Thanks to @dberlin!
  #5393 #5397
* macOS: Fixed notch avoidance padding in full screen mode. Thanks to @mbaird!
  #5515 #3807
* Render invalidation issue when closing tabs other than the last tab. Thanks
  to @Mrreadiness! #5441 #5304
* Search mode now accepts composed input from the IME. Thanks to @kenchou! #5564
* Quick select mode will now accept unix paths with `//` in them. #5763
* blob leases (for image rendering) could be removed by temporary directory
  cleaners, resulting in issues with rendering. We no longer store these
  in a pure temporary directory; they live in a cache dir, and if someone
  does remove or truncate these files, we now convert that error case
  into blank frame(s). #5422 #4657
* PaneInformation object returned `pixel_width` when asked to return the
  `pixel_height`.
* ssh: we now explicitly kill and reap the `ProxyCommand` associated
  with an ssh session. Thanks to @daaku! #5494 #5479
* `default_ssh_domains()` didn't use the default local echo threshold
  for ssh domains. #5547
* multiplexer: internal PKI certificate now supplements its list of
  "Subject Alternative Names" with the list of canonical hostnames returned
  for the local system via `getaddrinfo`. #5543
* DECSLRM incorrectly clamped the left margin based on the terminal height
  instead of the terminal width. Thanks to @j4james and @tmccombs! #5871 #5750
* Scrollback position was incorrectly advanced when in alt-screen mode.
  Thanks to @tbung and @loops! #6099 #4607 #6186
* Wayland: Fixed potential panic on startup when monitors have changed are
  in the process of hot plugging when wezterm starts. Thanks to @loops! #6084
* macOS: explicitly set the window to sRGB colorspace to resolve incorrect
  colors on non-sRGB monitors. Thanks to @rianmcguire! #6063 #5824
* The bell would ring each window instead of just the window containing the
  pane where the bell is ringing. Thanks to @loops! #6012 #5985
* x11: transient errors in obtaining/setting the selection could cause
  wezterm to exit. Thanks to @loops! #6135 #5482 #6128
* Wayland: potential panic when working with the clipboard. Thanks to @rengare!
  #5518
* multiplexer: could lose track of delta updates if the display changed
  while the current delta was being computed. Thanks to @loops! #5981
* Plugins: normalize the plugin path to exclude trailing slashes. Thanks to
  @joncrangle! #5883
* zooming a tab might not work if you also recently used `pane:activate()`.
  Thanks to @SpyMachine! #5964 #5928
* `pane:current_working_dir.file_path` returned incorrect results for
  paths that contained `#` or `?` characters. Thanks to @loops! #6158 #6171
* wayland: issues with losing maximized or tiled state when switching between
  applications. Thanks to @aliaksandr-trush! #4568 #5897
* Mouse multiple button click requires pixel precision. Thanks to @jbiosca78!
  #6475 #6476
* background image with width/height set to `Contain` used the wrong aspect
  ratio. Thanks to @saltkid! #6554 #3708 #4407
* wayland: `hide_cursor: Missing enter event serial` error. Thanks to @jmbaur!
  #6548 #5760
* wayland: issue tiled and maximized window states. Thanks to
  @aliaksandr-trush! #6545 #6262
* wayland: potential crash on monitors with scale > 1. Thanks to @MaeIsBad!
  #6508 #5406
* Opening an `InputSelector` while some other overlay was active could
  result in an error. Thanks to @mikkasendke! #6403
* Improved handling of implicit hyperlinks with parentheses. Thanks to
  @psyclaudeZ! #6391
* macOS: Key repeat would stop when switching between held keys when `use_ime`
  was enabled. Thanks @psyclaudeZ! #6391 #4061
* `wezterm cli split-pane --move-pane-id` could kill panes. Thanks to @scauligi!
  #6028 #6029
* Glyph '┽', was rendering as '┥' when `custom_block_glyphs` was enabled.
  Thanks to @bew! #6661 #6655
* Windows: stack overflow when using `tmux -CC`. Thanks to @joexue! #6704 #6671
* `get_text_from_semantic_zone` didn't include the last line of text. Thanks to
  @mgpinf! #6248 #5806 #5346
* Deadlock when a domain detaches due to SSH timeout. Thanks to @joexue! #6749
  #6750
* Panic when rewrapping very very long lines. #6729
* CUP position parameters were mandatory when they should have been optional.
  Thanks to @wojciech-graj! #6860
* Long CSI sequences were not parsed correctly. Thanks to @jdugan6240! #5161
  #6194
* IBus IME working unreliably. Thanks to @pjm0616! #5125
* Pixel aliasing issue when using
  [window_content_alignment](config/lua/config/window_content_alignment.md) =
  `Center`. Thanks to @juster-0! #6929 #6928 #6823
* Passing a `SpawnCommand` to the `SwitchToWorkspace` assignment would ignore
  `set_environment_variables`. Thanks to @vincentbesanceney! #6850 #6845
* `libssh` based ssh sessions will now respect `ServerAliveInterval`. #4023
* macOS: prevent infinite loop in `Services` menu validation. Thanks to @cpick!
  #7098 #6738 #6833 #6864
* Wayland: fixed issue with fractional scaling. Thanks to @kalebo! #7277
* Incorrect boundary condition in renderstate. Thanks to @I-Info! #7274
* MacOS: fix memory leak in macOS MetalLayer management. Thanks to @I-Info!
  #7283
* [max_fps](config/lua/config/max_fps.md) can now be set to values larger than
  `255`. Thanks to @beckend! #7366
* macOS: Fix toast notifications. Thanks to @nikhilm! #7483
* termwiz: Fixed parsing of fragmented mouse reporting sequence. Thanks to
  @jgiannuzzi! #7076 #7504
* docs: add missing `panes` field to [TabInformation](config/lua/TabInformation.md).
  Thanks to @KevinSilvester! #7710
* Windows: Fixed a crash (RefCell borrow conflict) when toggling IME (e.g.
  pressing Hankaku/Zenkaku) after splitting a pane. Thanks to @shiena! #7529
* Fixed a stack overflow that could occur on Windows (and other platforms) when
  the process tree contained cycles due to PID reuse. Thanks to @novoselov-ab! #7706
* Wayland: Fixed clipboard paste failing in windows that were not focused when
  the copy happened. Thanks to @bew and @XeroOl! #7863
* Fixed an infinite loop in pane search when the regex engine hit a backtracking
  limit. Thanks to @bew! #7864
* Fix ESC key encoding in kitty mode with disambiguate flag enabled.
  Thanks to @Felixoid and @the-mikedavis! #7787
* Fixed two divide-by-zero crashes in Kitty inline image placement when a program requests
  a zero-sized placement (e.g. `w=0`/`h=0`), or displaying a cell-sized image on a pane
  whose pty reported no pixel dimensions (e.g. in `tmux -CC` domain).
  Such images are now refused instead of taking down the pane. Thanks to @zakrad! #6344
* Fix render loop freeze when closing workspaces. Thanks to @JafarAbdi! #7444
* Wayland: the titlebar is now correctly hidden when `window_decorations`
  does not include `TITLE`. Thanks to @jchantrell! #7601
* macOS: the window can no longer be dragged by its top row when it has no
  decorations. Thanks to @draconivis! #7967
* `tmux -CC` sessions: fix keyboard input stalling (was a typo when running `send-keys`)
  Thanks to @bew! #8001
* IME: committed text is now handled correctly in prompt overlays such as
  `PromptInputLine` and the debug overlay. Thanks to @dyxushuai! #7556

#### Updated
* Bundled conpty.dll and OpenConsole.exe to build 1.22.250204002.nupkg
* Bundled harfbuzz to 11.2.1
* Bundled libssh to 0.11.1
* Bundled freetype to 2.13.3
* Bundled Nerd Font Symbols font to v3.3.0
* Bundled Noto Color Emoji font to 2.047
* image crate to 0.25, which means that JPEG images are now decoded via
  [zune-jpeg](https://docs.rs/zune-jpeg/latest/zune_jpeg/), which improves
  handling of non-conforming jpeg images. #5365
* Color schemes: [Astrodark (Gogh)](colorschemes/a/index.md#astrodark-gogh),
  [Blue Dolphin (Gogh)](colorschemes/b/index.md#blue-dolphin-gogh),
  [Breadog (Gogh)](colorschemes/b/index.md#breadog-gogh),
  [Butrin (Gogh)](colorschemes/b/index.md#butrin-gogh),
  [City Lights (Gogh)](colorschemes/c/index.md#city-lights-gogh),
  [CutiePro](colorschemes/c/index.md#cutiepro),
  [Ef-Dream](colorschemes/e/index.md#ef-dream),
  [Ef-Reverie](colorschemes/e/index.md#ef-reverie),
  [Eldritch](colorschemes/e/index.md#eldritch),
  [Everforest Dark Hard (Gogh)](colorschemes/e/index.md#everforest-dark-hard-gogh),
  [Everforest Dark Medium (Gogh)](colorschemes/e/index.md#everforest-dark-medium-gogh),
  [Everforest Dark Soft (Gogh)](colorschemes/e/index.md#everforest-dark-soft-gogh),
  [Everforest Light Hard (Gogh)](colorschemes/e/index.md#everforest-light-hard-gogh),
  [Everforest Light Medium (Gogh)](colorschemes/e/index.md#everforest-light-medium-gogh),
  [Everforest Light Soft (Gogh)](colorschemes/e/index.md#everforest-light-soft-gogh),
  [Github Light (Gogh)](colorschemes/g/index.md#github-light-gogh),
  [Iceberg (Gogh)](colorschemes/i/index.md#iceberg-gogh),
  [Kanagawa Dragon (Gogh)](colorschemes/k/index.md#kanagawa-dragon-gogh),
  [kurokula](colorschemes/k/index.md#kurokula),
  [Mellifluous](colorschemes/m/index.md#mellifluous),
  [Miramare (Gogh)](colorschemes/m/index.md#miramare-gogh),
  [Modus Operandi (Gogh)](colorschemes/m/index.md#modus-operandi-gogh),
  [Modus Operandi Tinted (Gogh)](colorschemes/m/index.md#modus-operandi-tinted-gogh),
  [Modus Vivendi (Gogh)](colorschemes/m/index.md#modus-vivendi-gogh),
  [Modus Vivendi Tinted (Gogh)](colorschemes/m/index.md#modus-vivendi-tinted-gogh),
  [NvimDark](colorschemes/n/index.md#nvimdark),
  [NvimLight](colorschemes/n/index.md#nvimlight),
  [Paper (Gogh)](colorschemes/p/index.md#paper-gogh),
  [Quiet (Gogh)](colorschemes/q/index.md#quiet-gogh),
  [Selenized Black (Gogh)](colorschemes/s/index.md#selenized-black-gogh),
  [Selenized White (Gogh)](colorschemes/s/index.md#selenized-white-gogh),
  [Seoul256 (Gogh)](colorschemes/s/index.md#seoul256-gogh),
  [Seoul256 Light (Gogh)](colorschemes/s/index.md#seoul256-light-gogh),
  [Sparky (Gogh)](colorschemes/s/index.md#sparky-gogh),
  [Sugarplum](colorschemes/s/index.md#sugarplum),
  [Vesper](colorschemes/v/index.md#vesper)
* flatpak: runtime bumped from 23.08 to 25.08. #7767

### 20240203-110809-5046fc22

#### Changed
* The default for
  [freetype_load_flags](config/lua/config/freetype_load_flags.md) is now
  `NO_HINTING` when the dpi is >= 100, otherwise `DEFAULT`. #4902
* `wezterm -e` will now wait for the spawned program to terminate before
  it will itself terminate. Thanks to @vimpostor! #4535 #4523
* Reverted the text cursor cell dimension change due to overwhelming and
  sometimes toxic feedback. #2882
#### New
* We now show the Lua version in the debug overlay. Thanks to @bbkane! #4943
* `wezterm start --new-tab` and `wezterm connect --new-tab` to request a new
  tab rather than a new window when spawning via an existing GUI instance.
  The new [prefer_to_spawn_tabs](config/lua/config/prefer_to_spawn_tabs.md)
  option allows you to make this happen by default. ?4854 ?4946
#### Fixed
* It was not possible to specify `freetype_load_flags = 'DEFAULT'`. #4902
* macOS: fallback fonts could select thin or otherwise unspecified font
  attributes. #4808
* Changing the palette via escape sequences didn't invalidate caches
  correctly, so those escapes sequences wouldn't take effect. #4932 #2635
* Unix: spawning a command using a relative path, with the cwd set to a
  directory that contains a directory with the same name as the relative
  path to the command would fail with an obscure error message. #4920
* x11: incorrect handling of the space key when `grp:win_space_toggle`
  was enabled via `setxkbmap`. #4910
* `wezterm set-working-directory` and `wezterm imgcat` didn't correctly
  apply tmux passthrough escape encoding. #4940
* Tab bar wouldn't immediately reflect the result of calling `tab:set_title`.
  #4941
* Command Palette: Missing space between keycaps on macOS. #4885
* macOS: stale/invalid cwd used when spawning new panes when shell integration
  is NOT in use. #4811
* Command Palette: would show default key assignments next to actions even
  if `disable_default_key_bindings` was configured. #4724

### 20240128-202157-1e552d76

#### Changed
