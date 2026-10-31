"""처음 연결하거나 DB를 추가할 때만 여는 로컬 설정창."""
from __future__ import annotations

import uuid


def show(store, engine, profile_id=None):
    if engine == 'demo':
        raise ValueError('실습에는 인증정보가 필요하지 않습니다. demo-init으로 시작해 주세요.')
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        raise ValueError('이 Python에는 로컬 설정창이 없습니다. tkinter가 포함된 Python을 사용해 주세요.') from None
    current = store.profile(profile_id) if profile_id else {}
    if current and current['engine'] != engine:
        raise ValueError('다른 스킬의 연결 설정은 이 창에서 수정하지 않습니다.')
    existing = store.secrets(profile_id) if profile_id else {}
    root = tk.Tk()
    root.title('데이터 조회 연결 설정')
    root.geometry('640x650')
    root.minsize(540, 620)
    root.configure(bg='#f5f7fa')
    style = ttk.Style(root)
    style.configure('TLabel', font=('맑은 고딕',10))
    style.configure('TButton', font=('맑은 고딕',10), padding=8)
    frame = ttk.Frame(root, padding=22)
    frame.pack(fill='both', expand=True)
    frame.columnconfigure(1, weight=1)
    ttk.Label(frame, text='조회할 데이터 연결', font=('맑은 고딕',18,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,10))
    ttk.Label(frame, text='입력값은 이 PC에 저장합니다. 저장만으로 서버에 접속하지 않습니다.', wraplength=570).grid(row=1,column=0,columnspan=2,sticky='w',pady=(0,18))
    fields = {}
    row = 2
    def field(key, title, value='', secret=False):
        nonlocal row
        ttk.Label(frame,text=title).grid(row=row,column=0,sticky='nw',padx=(0,12),pady=7)
        variable = tk.StringVar(value=value)
        ttk.Entry(frame,textvariable=variable,show='●' if secret else '').grid(row=row,column=1,sticky='ew',pady=7)
        fields[key] = variable
        row += 1
    field('name','DB 표시 이름',current.get('name',''))
    if engine == 'oracle':
        field('user','아이디',existing.get('user',''))
        field('password','비밀번호',existing.get('password',''),True)
        ttk.Label(frame,text='DSN 접속 정보').grid(row=row,column=0,sticky='nw',pady=7)
        dsn = tk.Text(frame,height=9,font=('맑은 고딕',10),wrap='word')
        dsn.grid(row=row,column=1,sticky='nsew',pady=7)
        dsn.insert('1.0',existing.get('dsn',''))
        row += 1
        ttk.Label(frame,text='host:port/service 또는 여러 줄 TNS 접속 정보를 붙여 넣으세요.',wraplength=570).grid(row=row,column=0,columnspan=2,sticky='w')
        row += 1
    else:
        field('user_id','사번',existing.get('user_id',''))
        field('token','개인 토큰',existing.get('token',''),True)
        field('api_base','회사 API 주소',current.get('api_base',''))
        field('cluster','클러스터 이름 (선택)',current.get('cluster',''))
        field('tls_ca','인증서 파일 (선택)',current.get('tls_ca',''))
        allow_start = tk.BooleanVar(value=current.get('allow_cluster_start',False))
        allow_http = tk.BooleanVar(value=current.get('allow_http',False))
        ttk.Checkbutton(frame,text='조회할 때 내 클러스터 준비/기동을 허용합니다.',variable=allow_start).grid(row=row,column=0,columnspan=2,sticky='w',pady=8)
        row += 1
        ttk.Checkbutton(frame,text='회사에서 지정한 HTTP 주소 사용을 확인했습니다.',variable=allow_http).grid(row=row,column=0,columnspan=2,sticky='w',pady=8)
        row += 1
    ttk.Label(frame,text='개인 설정은 평문 env 파일입니다. 공유하거나 배포 ZIP에 넣지 마세요.',wraplength=570).grid(row=row,column=0,columnspan=2,sticky='w',pady=(15,8))
    row += 1
    outcome = {'ok':False,'status':'cancelled','message':'연결 설정을 저장하지 않았습니다.'}
    def save():
        try:
            profile = dict(current) if current else {'id':'db_'+uuid.uuid4().hex[:12], 'engine':engine}
            profile['name'] = fields['name'].get().strip()
            if engine == 'oracle':
                secrets = {'user':fields['user'].get().strip(),'password':fields['password'].get(), 'dsn':dsn.get('1.0','end-1c').strip()}
            else:
                from urllib.parse import urlsplit
                base = fields['api_base'].get().strip().rstrip('/')
                parsed = urlsplit(base)
                if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError('아이디나 토큰이 없는 올바른 회사 API 주소를 입력해 주세요.')
                if parsed.scheme == 'http' and not allow_http.get():
                    raise ValueError('HTTP 주소 사용 여부를 확인해 주세요. 주소를 임의로 바꾸지는 않습니다.')
                profile.update(api_base=base,cluster=fields['cluster'].get().strip(),tls_ca=fields['tls_ca'].get().strip(),
                               allow_http=allow_http.get(),allow_cluster_start=allow_start.get())
                secrets = {'user_id':fields['user_id'].get().strip(),'token':fields['token'].get()}
            if any(not value for value in secrets.values()):
                raise ValueError('연결에 필요한 값을 모두 입력해 주세요.')
            info = store.save_profile(profile,secrets,replace=bool(current))
            outcome.update(ok=True,status='saved',profile=info,message='연결 설정을 저장했습니다. 실제 접속은 아직 하지 않았습니다.')
            root.destroy()
        except ValueError as error:
            messagebox.showerror('입력 확인',str(error),parent=root)
        except Exception:
            messagebox.showerror('저장 확인','설정을 저장하지 못했습니다. 개인 저장소의 쓰기 권한을 확인해 주세요.',parent=root)
    buttons = ttk.Frame(frame)
    buttons.grid(row=row,column=0,columnspan=2,sticky='e',pady=15)
    ttk.Button(buttons,text='취소',command=root.destroy).pack(side='right',padx=5)
    ttk.Button(buttons,text='저장',command=save).pack(side='right')
    root.mainloop()
    return outcome
