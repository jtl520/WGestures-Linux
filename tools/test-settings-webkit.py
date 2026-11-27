#!/usr/bin/env python3
"""Exercise the actual WebKit/native bridge with an isolated configuration."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", required=True)
args = parser.parse_args()
output = Path(args.output_dir).resolve()
output.mkdir(parents=True, exist_ok=True)
temporary = tempfile.TemporaryDirectory(prefix="crossgestures-ui-")
os.environ["XDG_CONFIG_HOME"] = temporary.name
os.environ["GSETTINGS_BACKEND"] = "memory"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "linux"))

from wgestures.webprefs import SettingsWindow, Gtk, GLib, WebKit2

application = Gtk.Application(application_id="com.jtl520.CrossGestures.SettingsTest")
application.register(None)
window = SettingsWindow(application)
window.show_all()
exit_status = [1]
stage = [0]


def evaluate(script, callback):
    def completed(web, result, _data):
        try:
            value = web.run_javascript_finish(result).get_js_value().to_string()
            callback(value)
        except Exception as error:
            print("JavaScript failure:", error, flush=True)
            Gtk.main_quit()
    window.web.run_javascript(script, None, completed, None)


def snapshot(name, callback):
    def completed(web, result, _data):
        try:
            surface = web.get_snapshot_finish(result)
            surface.write_to_png(str(output / name))
            callback()
        except Exception as error:
            print("Snapshot failure:", error, flush=True)
            Gtk.main_quit()
    window.web.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, completed, None)


script = r"""
(async () => {
 const wait = async predicate => { for(let i=0;i<150;i++){if(predicate()) return;await new Promise(r=>setTimeout(r,40));} throw new Error('UI timeout'); };
 const check = (value, message) => { if(!value) throw new Error(message); };
 try {
  check(Array.from(document.fonts).some(f=>f.family.includes('CrossGestures UI') && f.status==='loaded'),'Bundled UI font did not load');
  document.querySelector('[data-page="gestures"]').click();
  check(document.querySelectorAll('.gesture-item').length===4,'Default gestures missing');
  document.querySelector('.toolbar .primary').click();
  let fields=document.querySelectorAll('#dialog-body input'); fields[0].value='界面验收';
  document.querySelectorAll('.direction-tools button')[6].click();
  document.querySelectorAll('#dialog-body select')[1].value='NoopAction';
  document.querySelectorAll('#dialog-body select')[1].dispatchEvent(new Event('change'));
  document.querySelector('#dialog-form').requestSubmit();
  await wait(()=>document.querySelector('#modal').hidden);
  check(state.profiles[0].gestures.length===5,'Gesture was not saved');
  const saved=state.profiles[0].gestures.find(g=>g.name==='界面验收');
  check(saved.action.type==='NoopAction','Wrong action persisted');
  // Attempting a duplicate must leave the native store untouched.
  let rejected=false;
  try {await rpc('gestureSave',{revision:state.revision,profileId:'global',name:'重复',button:'right',directions:['up'],action:{type:'NoopAction'}});}catch(e){rejected=true;}
  check(rejected,'Duplicate gesture accepted');
  await mutate('gestureDelete',{profileId:'global',id:saved.id});
  document.querySelector('[data-page="profiles"]').click();
  document.querySelector('.toolbar .primary').click();
  fields=document.querySelectorAll('#dialog-body input');fields[0].value='界面验收应用';fields[3].value='CrossGesturesTest';
  document.querySelector('#dialog-form').requestSubmit();
  await wait(()=>document.querySelector('#modal').hidden);
  check(state.profiles.length===2,'Application was not saved');
  await mutate('profileDelete',{id:state.profiles[1].id});
  document.querySelector('[data-page="general"]').click();
  const width=document.querySelector('input[aria-label="轨迹宽度"]');width.value='6.5';width.dispatchEvent(new Event('change'));
  await wait(()=>!busy);check(state.settings['path-width']===6.5,'Setting was not saved');
  await mutate('setting',{key:'path-width',value:4});
  window.__smoke={done:true,ok:true,checks:9};
 } catch(error) {window.__smoke={done:true,ok:false,error:error.stack};}
})();
'started';
"""


def poll():
    def result(value):
        status = json.loads(value)
        if status.get("ready") and stage[0] == 0:
            stage[0] = 1
            snapshot("ubuntu-general.png", lambda: evaluate(script, lambda _v: None))
        elif status.get("done") and stage[0] == 1:
            stage[0] = 2
            (output / "webkit-result.json").write_text(json.dumps(status, ensure_ascii=False, indent=2))
            print(json.dumps(status, ensure_ascii=False), flush=True)
            if not status.get("ok"):
                Gtk.main_quit()
                return
            evaluate("document.querySelector('[data-page=gestures]').click(); 'ok'", lambda _v: GLib.timeout_add(200, capture_gestures))
    evaluate("JSON.stringify(window.__smoke || {ready: typeof state !== 'undefined' && !!state && document.fonts.status==='loaded'})", result)
    return stage[0] < 2


def capture_gestures():
    def captured():
        evaluate("editGesture(state.profiles[0].gestures[0]); 'ok'", lambda _v: GLib.timeout_add(200, capture_dialog))
    snapshot("ubuntu-gestures.png", captured)
    return False


def capture_dialog():
    def captured():
        evaluate("closeDialog();document.querySelector('[data-page=general]').click();'ok'", lambda _v: None)
        window.resize(660, 600)
        GLib.timeout_add(500, capture_narrow)
    snapshot("ubuntu-edit-gesture.png", captured)
    return False


def capture_narrow():
    def captured():
        exit_status[0] = 0
        Gtk.main_quit()
    snapshot("ubuntu-narrow.png", captured)
    return False


GLib.timeout_add(150, poll)
GLib.timeout_add_seconds(40, lambda: (print("UI test timeout", flush=True), Gtk.main_quit(), False)[2])
Gtk.main()
window.destroy()
temporary.cleanup()
sys.exit(exit_status[0])
