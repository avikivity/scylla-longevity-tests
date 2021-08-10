import inspect
import logging
import multiprocessing
import sys
import threading
import traceback


LOGGER = logging.getLogger(__name__)


def get_thread_stacktrace(thread):  # pylint: disable=no-self-use
    frame = sys._current_frames().get(thread.ident, None)  # pylint: disable=protected-access
    output = []
    for filename, lineno, name, line in traceback.extract_stack(frame):
        output.append('File: "%s", line %d, in %s' % (filename,
                                                      lineno, name))
        if line:
            output.append("  %s" % (line.strip()))
    return '\n'.join(output)


def gather_live_threads_and_dump_to_file(dump_file_path: str) -> bool:
    if not threading.active_count():
        return False
    source_modules = []
    result = False
    with open(dump_file_path, 'a') as log_file:
        for thread in threading.enumerate():
            if thread is threading.current_thread():
                continue
            result = True
            source = '<no code available>'
            module = 'Unknown'
            if thread.__class__ is threading.Thread:
                if thread.run.__func__ is not threading.Thread.run:
                    module = thread.run.__module__
                    source = inspect.getsource(thread.run)
                elif getattr(thread, '_target', None):
                    module = thread._target.__module__  # pylint: disable=protected-access
                    source = inspect.getsource(thread._target)  # pylint: disable=protected-access
            else:
                module = thread.__module__
                source = inspect.getsource(thread.__class__)
            if module not in source_modules:
                source_modules.append(module)
            log_file.write(f"========= Thread {thread.name} from {module} =========\n")
            log_file.write(f"========= SOURCE =========\n{source}\n")
            log_file.write(f"========= STACK TRACE =========\n{get_thread_stacktrace(thread)}\n")
            log_file.write(f"========= END OF Thread {thread.name} from {module} =========\n")
    if result:
        LOGGER.error("There are some threads left alive from following modules: %s", ",".join(source_modules))
    return result


def gather_live_processes_and_dump_to_file(dump_file_path: str) -> bool:
    if not multiprocessing.active_children():
        return False
    source_modules = []
    with open(dump_file_path, 'a') as log_file:
        for proc in multiprocessing.active_children():
            source = '<no code available>'
            module = 'Unknown'
            if proc.__class__ is multiprocessing.Process:
                if proc.run.__func__ != multiprocessing.Process.run:
                    module = proc.run.__module__
                    source = inspect.getsource(proc.run)
            else:
                module = proc.__module__
                source = inspect.getsource(proc.__class__)
            if module not in source_modules:
                source_modules.append(module)
            log_file.write(f"========= Process {proc.name} from {module} =========\n")
            log_file.write(f"========= SOURCE =========\n{source}\n")
            log_file.write(f"========= END OF Process {proc.name} from {module}  =========\n")
    LOGGER.error("There are some processes left alive from the following modules %s", ",".join(source_modules))
    return True
