"""The 20 demo FAQ articles in English and Japanese (Part C, section 9).

Each entry is (category, title_en, body_en, title_ja, body_ja). Categories use
the same values as ticket categories, so the FAQ page and the chatbot can
group and filter articles the same way tickets are grouped. Bodies are plain
text with one step per line; the frontend shows them as written.
"""

FAQ_ARTICLES: list[tuple[str, str, str, str, str]] = [
    (
        "password",
        "How do I reset my password?",
        "1. Open the self-service password reset page from the company portal.\n"
        "2. Enter your company email address and complete the verification step.\n"
        "3. Choose a new password with at least 12 characters, mixing letters, numbers, and symbols.\n"
        "4. Sign in again on every device, including your phone mail app.\n"
        "If verification fails, create a ticket in the Password category. IT will never ask for your password.",
        "パスワードをリセットするには",
        "1. 社内ポータルからセルフサービスのパスワードリセット画面を開きます。\n"
        "2. 会社のメールアドレスを入力し、本人確認を完了します。\n"
        "3. 英字・数字・記号を組み合わせた12文字以上の新しいパスワードを設定します。\n"
        "4. スマートフォンのメールアプリを含め、すべての端末で再度サインインします。\n"
        "本人確認ができない場合は「パスワード」カテゴリで問い合わせを登録してください。"
        "IT部門がパスワードを聞くことはありません。",
    ),
    (
        "account",
        "My account is locked",
        "Accounts lock after several failed sign-in attempts.\n"
        "1. Wait 15 minutes; the lock is released automatically.\n"
        "2. Check that Caps Lock is off and that the keyboard is set to the right input mode.\n"
        "3. If an old password is saved on another device (phone mail, tablet), update or remove it, "
        "because it keeps retrying in the background.\n"
        "If you are still locked out after 15 minutes, create a ticket in the Account category.",
        "アカウントがロックされた",
        "サインインに何度か失敗すると、アカウントがロックされます。\n"
        "1. 15分待つと自動的に解除されます。\n"
        "2. Caps Lockがオフになっているか、入力モードが正しいかを確認します。\n"
        "3. スマートフォンのメールやタブレットに古いパスワードが保存されている場合は、更新または削除してください。"
        "裏で自動的に再試行され、再びロックされる原因になります。\n"
        "15分たっても解除されない場合は「アカウント」カテゴリで問い合わせを登録してください。",
    ),
    (
        "account",
        "Setting up multi-factor authentication (MFA)",
        "1. Install Microsoft Authenticator on your company or personal smartphone.\n"
        "2. On a PC, open the security info page and choose Add sign-in method, then Authenticator app.\n"
        "3. Scan the QR code shown on the PC with the app.\n"
        "4. Approve the test notification to finish.\n"
        "When you change phones, register the new phone before resetting the old one. "
        "If you have already lost access, create a ticket in the Account category.",
        "多要素認証（MFA）の設定方法",
        "1. 会社支給または個人のスマートフォンにMicrosoft Authenticatorをインストールします。\n"
        "2. PCでセキュリティ情報のページを開き、「サインイン方法の追加」から「認証アプリ」を選びます。\n"
        "3. PCに表示されたQRコードをアプリで読み取ります。\n"
        "4. テスト通知を承認すると設定が完了します。\n"
        "機種変更の際は、古い端末を初期化する前に新しい端末を登録してください。"
        "すでに認証できなくなっている場合は「アカウント」カテゴリで問い合わせを登録してください。",
    ),
    (
        "vpn",
        "VPN cannot connect",
        "1. Check that your home or hotel internet works by opening any public website.\n"
        "2. Quit the VPN client completely and start it again.\n"
        "3. Confirm the date and time on your PC are correct; a wrong clock breaks the certificate check.\n"
        "4. Restart the PC and try once more.\n"
        "5. If you see an authentication error, approve the MFA notification on your phone within the time limit.\n"
        "If it still fails, create a ticket in the VPN category with the exact error message and the time it happened.",
        "VPNに接続できない",
        "1. 一般のWebサイトを開き、自宅やホテルのインターネット回線が使えるか確認します。\n"
        "2. VPNクライアントを完全に終了してから、もう一度起動します。\n"
        "3. PCの日付と時刻が正しいか確認します。時刻がずれていると証明書の確認に失敗します。\n"
        "4. PCを再起動して、もう一度接続します。\n"
        "5. 認証エラーが出る場合は、スマートフォンに届くMFAの通知を時間内に承認してください。\n"
        "解決しない場合は、表示されたエラーメッセージと発生時刻を添えて「VPN」カテゴリで問い合わせを登録してください。",
    ),
    (
        "email",
        "Outlook is not syncing",
        "1. Check the status bar at the bottom of Outlook. If it says Disconnected or Working offline, "
        "turn off Work Offline on the Send / Receive tab.\n"
        "2. Close Outlook and open it again.\n"
        "3. Open Outlook on the web. If new mail appears there, the problem is on the PC; "
        "if not, it is on the mailbox side.\n"
        "4. If your mailbox is almost full, delete or archive large items.\n"
        "If mail still does not arrive, create a ticket in the Email category.",
        "Outlookが同期されない",
        "1. Outlook下部のステータスバーを確認します。「切断」や「オフライン作業中」と表示されている場合は、"
        "［送受信］タブの「オフライン作業」をオフにします。\n"
        "2. Outlookを終了し、もう一度起動します。\n"
        "3. Web版のOutlookを開きます。そちらに新しいメールが届いていればPC側、届いていなければメールボックス側の問題です。\n"
        "4. メールボックスの容量がいっぱいに近い場合は、大きなメールを削除またはアーカイブします。\n"
        "それでも受信できない場合は「メール」カテゴリで問い合わせを登録してください。",
    ),
    (
        "software",
        "No sound or microphone in Teams",
        "1. In a Teams meeting, open More, then Settings, then Device settings.\n"
        "2. Choose the headset or speaker you are actually using for both speaker and microphone.\n"
        "3. Make a test call to check sound and microphone.\n"
        "4. Check that the headset mute switch is off and that Windows privacy settings allow microphone access.\n"
        "5. Restart Teams after plugging in a new headset.\n"
        "If the problem continues, create a ticket in the Software category with the headset model.",
        "Teamsで音が出ない・マイクが使えない",
        "1. Teams会議中に「その他」から「設定」、「デバイスの設定」を開きます。\n"
        "2. スピーカーとマイクの両方で、実際に使っているヘッドセットやスピーカーを選びます。\n"
        "3. テスト通話で音声とマイクを確認します。\n"
        "4. ヘッドセットのミュートスイッチがオフになっているか、Windowsのプライバシー設定でマイクの使用が許可されているかを確認します。\n"
        "5. 新しいヘッドセットを接続した後は、Teamsを再起動します。\n"
        "改善しない場合は、ヘッドセットの機種名を添えて「ソフトウェア」カテゴリで問い合わせを登録してください。",
    ),
    (
        "hardware",
        "The printer is not found",
        "1. Check that the printer is on and shows no error on its panel.\n"
        "2. Make sure your PC is on the office network, not a guest Wi-Fi.\n"
        "3. Open Settings, then Printers & scanners, and choose Add device. Office printers are named by floor, "
        "for example 3F-Copier-01.\n"
        "4. If the printer is listed but jobs stay in the queue, delete the stuck jobs and print again.\n"
        "If the printer still does not appear, create a ticket in the Hardware category with the printer name.",
        "プリンターが見つからない",
        "1. プリンターの電源が入っていて、操作パネルにエラーが出ていないか確認します。\n"
        "2. PCがゲスト用Wi-Fiではなく、社内ネットワークに接続されているか確認します。\n"
        "3. ［設定］の「プリンターとスキャナー」から「デバイスの追加」を選びます。"
        "社内のプリンターは「3F-Copier-01」のようにフロア名で登録されています。\n"
        "4. 一覧には表示されるのに印刷が待ち状態のままの場合は、止まっているジョブを削除してから再度印刷します。\n"
        "それでも表示されない場合は、プリンター名を添えて「ハードウェア」カテゴリで問い合わせを登録してください。",
    ),
    (
        "network",
        "Wi-Fi does not connect",
        "1. Turn Wi-Fi off and on again from the taskbar.\n"
        "2. Choose the office network, not the guest network. Company PCs connect automatically with their certificate.\n"
        "3. If the network asks for a password, do not type your account password; "
        "this usually means the certificate is missing.\n"
        "4. Restart the PC so the latest settings from Intune are applied.\n"
        "If only your PC cannot connect, create a ticket in the Network category. "
        "If nobody nearby can connect, tell the IT team directly.",
        "Wi-Fiにつながらない",
        "1. タスクバーからWi-Fiを一度オフにして、もう一度オンにします。\n"
        "2. ゲスト用ではなく社内用のネットワークを選びます。会社のPCは証明書で自動的に接続されます。\n"
        "3. パスワードの入力を求められても、アカウントのパスワードは入力しないでください。証明書が入っていない可能性があります。\n"
        "4. PCを再起動して、Intuneから最新の設定を反映させます。\n"
        "自分のPCだけがつながらない場合は「ネットワーク」カテゴリで問い合わせを登録してください。"
        "周りの人も全員つながらない場合は、IT部門に直接連絡してください。",
    ),
    (
        "laptop",
        "First sign-in on a new PC (Windows Autopilot)",
        "1. Connect the PC to power and to the office network or your home Wi-Fi.\n"
        "2. Choose the language and keyboard, then sign in with your company email address.\n"
        "3. Autopilot now installs company settings and apps. This can take 30 to 60 minutes; "
        "do not turn the PC off.\n"
        "4. Set up Windows Hello (PIN or face) when asked.\n"
        "5. After the desktop appears, open Company Portal and check that required apps are installed.\n"
        "If setup stops with an error code, take a photo of the screen and create a ticket in the Laptop category.",
        "新しいPCの初回サインイン（Windows Autopilot）",
        "1. PCを電源につなぎ、社内ネットワークまたは自宅のWi-Fiに接続します。\n"
        "2. 言語とキーボードを選び、会社のメールアドレスでサインインします。\n"
        "3. Autopilotにより会社の設定とアプリが自動でインストールされます。30分から60分ほどかかることがありますので、電源を切らないでください。\n"
        "4. 画面の案内に従ってWindows Hello（PINまたは顔認証）を設定します。\n"
        "5. デスクトップが表示されたら、ポータルサイト（Company Portal）を開き、必須アプリがインストールされているか確認します。\n"
        "エラーコードが表示されて止まった場合は、画面を撮影して「ノートPC」カテゴリで問い合わせを登録してください。",
    ),
    (
        "laptop",
        "Intune says my device is not compliant",
        "A device is marked non-compliant when it misses a company security rule.\n"
        "1. Open Company Portal, select your device, and choose Check status. It lists what is wrong.\n"
        "2. Common causes: Windows updates not installed, BitLocker off, or the device has not checked in for many days.\n"
        "3. Install pending updates, restart, and choose Check status again.\n"
        "4. The status can take up to an hour to refresh after you fix the issue.\n"
        "If the device stays non-compliant, create a ticket in the Laptop category with a screenshot of the status.",
        "Intuneで「非準拠」と表示される",
        "会社のセキュリティ基準を満たしていない端末は「非準拠」と判定されます。\n"
        "1. ポータルサイト（Company Portal）を開き、自分の端末を選んで「状態の確認」を押します。原因が一覧で表示されます。\n"
        "2. よくある原因は、Windows Updateが未適用、BitLockerがオフ、長期間チェックインしていない、などです。\n"
        "3. 保留中の更新プログラムをインストールして再起動し、もう一度「状態の確認」を押します。\n"
        "4. 対応後、状態が更新されるまで最大1時間ほどかかることがあります。\n"
        "非準拠のままの場合は、状態画面のスクリーンショットを添えて「ノートPC」カテゴリで問い合わせを登録してください。",
    ),
    (
        "smartphone",
        "Setting up a company iPhone",
        "1. Turn on the iPhone and connect to Wi-Fi. The company setup screen appears automatically.\n"
        "2. Sign in with your company email address when asked.\n"
        "3. Wait for Company Portal and the required apps (Outlook, Teams, Authenticator) to install.\n"
        "4. Open Outlook and sign in to start receiving mail.\n"
        "5. Set a passcode of six digits or more; the device will not become compliant without one.\n"
        "Do not sign in with a personal Apple ID during setup unless IT has asked you to.",
        "会社支給のiPhoneを設定する",
        "1. iPhoneの電源を入れ、Wi-Fiに接続すると、会社用の設定画面が自動的に表示されます。\n"
        "2. 案内に従って、会社のメールアドレスでサインインします。\n"
        "3. ポータルサイトと必須アプリ（Outlook、Teams、Authenticator）のインストールが終わるまで待ちます。\n"
        "4. Outlookを開いてサインインすると、メールの受信が始まります。\n"
        "5. 6桁以上のパスコードを設定してください。設定しないと準拠状態になりません。\n"
        "IT部門から指示がない限り、設定中に個人のApple IDでサインインしないでください。",
    ),
    (
        "smartphone",
        "Setting up an Android work profile",
        "1. Install Intune Company Portal from Google Play.\n"
        "2. Open it and sign in with your company email address.\n"
        "3. Follow the steps to create a work profile. Work apps appear with a briefcase icon.\n"
        "4. Install Outlook and Teams from the work profile's Play Store.\n"
        "Your personal apps, photos, and data stay outside the work profile, and IT cannot see them. "
        "If the setup fails, create a ticket in the Smartphone category with your phone model.",
        "Androidの仕事用プロファイルを設定する",
        "1. Google PlayからIntuneポータルサイト（Company Portal）をインストールします。\n"
        "2. アプリを開き、会社のメールアドレスでサインインします。\n"
        "3. 画面の案内に従って仕事用プロファイルを作成します。仕事用のアプリにはかばんのアイコンが付きます。\n"
        "4. 仕事用プロファイル内のPlayストアからOutlookとTeamsをインストールします。\n"
        "個人のアプリや写真、データは仕事用プロファイルの外にあり、IT部門から見ることはできません。"
        "設定がうまくいかない場合は、機種名を添えて「スマートフォン」カテゴリで問い合わせを登録してください。",
    ),
    (
        "hardware",
        "My device was lost or stolen",
        "Report it immediately, even outside working hours.\n"
        "1. Create a ticket in the Hardware category with priority Critical, or call the IT team.\n"
        "2. Include the device, when and where you last had it, and whether it was locked.\n"
        "3. IT will lock or wipe the device remotely and reset your sessions.\n"
        "4. Change your password after IT confirms the device is secured.\n"
        "For theft, also report it to the police and share the report number with IT.",
        "端末を紛失した・盗難にあった",
        "勤務時間外であっても、すぐに報告してください。\n"
        "1. 優先度「緊急」で「ハードウェア」カテゴリの問い合わせを登録するか、IT部門に電話します。\n"
        "2. 端末の種類、最後に手元にあった日時と場所、ロックがかかっていたかを記入します。\n"
        "3. IT部門が遠隔で端末のロックまたはワイプを行い、サインイン中のセッションを無効にします。\n"
        "4. IT部門から対応完了の連絡があったら、パスワードを変更してください。\n"
        "盗難の場合は警察にも届け出て、受理番号をIT部門に伝えてください。",
    ),
    (
        "hardware",
        "The screen is broken",
        "1. Stop using the device if the glass is cracked, to avoid injury.\n"
        "2. Back up any files that are not already in OneDrive.\n"
        "3. Create a ticket in the Hardware category with a photo of the damage and how it happened.\n"
        "4. IT will arrange a repair and, if needed, a loan device so you can keep working.\n"
        "Do not take company devices to a repair shop yourself.",
        "画面が割れた",
        "1. ガラスが割れている場合は、けがを防ぐため使用を中止してください。\n"
        "2. OneDriveに保存されていないファイルがあれば、バックアップします。\n"
        "3. 破損箇所の写真と状況を添えて、「ハードウェア」カテゴリで問い合わせを登録します。\n"
        "4. IT部門が修理を手配し、必要に応じて業務を続けられるよう代替機を貸し出します。\n"
        "会社の端末を、ご自身で修理店に持ち込まないでください。",
    ),
    (
        "software",
        "Requesting new software",
        "1. Check Company Portal first. Approved apps there can be installed by yourself with one click.\n"
        "2. If the software is not listed, create a ticket in the Software category.\n"
        "3. Include the software name, version, why you need it, and whether it needs a paid license.\n"
        "4. IT checks security and licensing, then adds it to Company Portal or installs it for you.\n"
        "Do not install software downloaded from the internet on company devices.",
        "ソフトウェアのインストールを依頼したい",
        "1. まずポータルサイト（Company Portal）を確認してください。掲載されている承認済みアプリは、自分でインストールできます。\n"
        "2. 掲載されていない場合は、「ソフトウェア」カテゴリで問い合わせを登録します。\n"
        "3. ソフトウェア名、バージョン、必要な理由、有償ライセンスが必要かどうかを記入してください。\n"
        "4. IT部門がセキュリティとライセンスを確認し、ポータルサイトへの追加またはインストールを行います。\n"
        "インターネットからダウンロードしたソフトウェアを、会社の端末にインストールしないでください。",
    ),
    (
        "tablet",
        "Borrowing a shared device",
        "Shared tablets and laptops are lent for business trips, events, and repairs.\n"
        "1. Create a ticket in the Tablet or Laptop category with the dates and purpose.\n"
        "2. IT prepares a device and records the loan with a due date.\n"
        "3. Pick it up from the IT desk and check that it turns on and charges.\n"
        "4. Return it by the due date. Overdue loans are flagged to IT and your manager.\n"
        "Shared devices are wiped after each loan, so do not store files only on the device.",
        "共用端末を借りたい",
        "共用のタブレットやノートPCは、出張・イベント・修理期間中などに貸し出しています。\n"
        "1. 利用期間と目的を記入して、「タブレット」または「ノートPC」カテゴリで問い合わせを登録します。\n"
        "2. IT部門が端末を準備し、返却期限を設定して貸出を記録します。\n"
        "3. ITデスクで受け取り、電源が入ることと充電できることを確認してください。\n"
        "4. 返却期限までに返却してください。期限を過ぎるとIT部門と上長に通知されます。\n"
        "共用端末は返却のたびに初期化されるため、端末だけにファイルを保存しないでください。",
    ),
    (
        "hardware",
        "Returning a device",
        "When you leave the company, change roles, or receive a replacement, return the old device to IT.\n"
        "1. Save your files to OneDrive and sign out of personal services.\n"
        "2. Bring the device, charger, and accessories to the IT desk.\n"
        "3. IT checks the condition and records the return. Devices are wiped before reuse.\n"
        "4. Tell IT about any damage; it is recorded, not charged, in normal use.\n"
        "Do not wipe or reset the device yourself unless IT asks you to.",
        "端末を返却する",
        "退職・異動・機種交換の際は、使っていた端末をIT部門に返却してください。\n"
        "1. ファイルをOneDriveに保存し、個人で使っていたサービスからサインアウトします。\n"
        "2. 端末本体、充電器、付属品をITデスクに持参します。\n"
        "3. IT部門が状態を確認して返却を記録します。端末は再利用の前に初期化されます。\n"
        "4. 破損がある場合は申し出てください。通常の使用による破損は記録のみで、費用の請求はありません。\n"
        "IT部門からの指示がない限り、ご自身で初期化しないでください。",
    ),
    (
        "laptop",
        "My PC is slow",
        "1. Restart the PC. Many issues clear after a full restart, not just closing the lid.\n"
        "2. Open Task Manager (Ctrl + Shift + Esc) and check which apps use the most CPU or memory.\n"
        "3. Close browser tabs and apps you are not using.\n"
        "4. Check that Windows updates have finished; updates often run in the background.\n"
        "5. Make sure at least 10 percent of the disk is free.\n"
        "If the PC is still slow, create a ticket in the Laptop category and mention when it started.",
        "PCの動作が遅い",
        "1. PCを再起動します。ふたを閉じるだけでなく、再起動すると改善することがよくあります。\n"
        "2. タスクマネージャー（Ctrl + Shift + Esc）を開き、CPUやメモリを多く使っているアプリを確認します。\n"
        "3. 使っていないブラウザーのタブやアプリを閉じます。\n"
        "4. Windows Updateが完了しているか確認します。更新はバックグラウンドで実行されていることがあります。\n"
        "5. ディスクの空き容量が10％以上あることを確認します。\n"
        "それでも遅い場合は、いつから遅くなったかを添えて「ノートPC」カテゴリで問い合わせを登録してください。",
    ),
    (
        "software",
        "OneDrive is not syncing",
        "1. Click the OneDrive cloud icon in the taskbar and read the status message.\n"
        "2. If it says Paused, choose Resume syncing.\n"
        "3. If a file has a red X, check that its name has no unsupported characters and the path is not too long.\n"
        "4. Sign out of OneDrive and sign in again if it keeps asking for your password.\n"
        "5. Check that your OneDrive storage is not full.\n"
        "If files still do not sync, create a ticket in the Software category with a screenshot of the error.",
        "OneDriveが同期されない",
        "1. タスクバーのOneDrive（雲）アイコンをクリックし、状態のメッセージを確認します。\n"
        "2. 「一時停止中」と表示されている場合は、「同期の再開」を選びます。\n"
        "3. 赤い×が付いたファイルは、使用できない文字がファイル名に含まれていないか、パスが長すぎないかを確認します。\n"
        "4. パスワードを何度も求められる場合は、OneDriveから一度サインアウトし、再度サインインします。\n"
        "5. OneDriveの保存容量がいっぱいになっていないか確認します。\n"
        "それでも同期されない場合は、エラー画面のスクリーンショットを添えて「ソフトウェア」カテゴリで問い合わせを登録してください。",
    ),
    (
        "laptop",
        "The disk is full",
        "1. Open Settings, then System, then Storage to see what uses the most space.\n"
        "2. Run Storage Sense or Disk Cleanup to remove temporary files.\n"
        "3. Empty the Recycle Bin and clear the Downloads folder.\n"
        "4. In OneDrive, set large folders to Free up space so they stay online only.\n"
        "5. Move large videos and archives to a team site instead of the PC.\n"
        "If less than 10 percent is still free, create a ticket in the Laptop category.",
        "ディスクの空き容量が足りない",
        "1. ［設定］の「システム」から「ストレージ」を開き、容量を多く使っているものを確認します。\n"
        "2. ストレージセンサーまたはディスククリーンアップで一時ファイルを削除します。\n"
        "3. ごみ箱を空にし、ダウンロードフォルダーを整理します。\n"
        "4. OneDriveで容量の大きいフォルダーを「空き容量を増やす」に設定し、オンラインのみに保存します。\n"
        "5. 大きな動画や圧縮ファイルは、PCではなくチームのサイトに移動します。\n"
        "それでも空き容量が10％未満の場合は「ノートPC」カテゴリで問い合わせを登録してください。",
    ),
]
