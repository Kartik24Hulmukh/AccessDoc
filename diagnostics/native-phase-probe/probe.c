#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <pythread.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
#ifdef __APPLE__
#include <mach/mach_time.h>
#include <pthread/qos.h>
static mach_timebase_info_data_t timebase;
#endif
#define BUDGET_NS UINT64_C(30000000)
#define QUANTUM_NS UINT64_C(1000000)
#define MAX_WAITS 32
#define CAPSULE_NAME "native_phase.held_lock"
typedef struct { PyThread_type_lock lock; int held; } Held;
typedef struct { uint64_t derived, enter, leave, cpu_enter, cpu_leave; long long us; int status; } Wait;
static uint64_t wall_ns(void) {
#ifdef __APPLE__
    return (uint64_t)(((__uint128_t)mach_absolute_time()*timebase.numer)/timebase.denom);
#else
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return 0;
    return (uint64_t)t.tv_sec*UINT64_C(1000000000)+(uint64_t)t.tv_nsec;
#endif
}
static uint64_t cpu_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t)) return 0;
    return (uint64_t)t.tv_sec*UINT64_C(1000000000)+(uint64_t)t.tv_nsec;
}
static void destroy_held(PyObject *capsule) {
    Held *h = PyCapsule_GetPointer(capsule, CAPSULE_NAME);
    if (!h) { PyErr_Clear(); return; }
    if (h->held) PyThread_release_lock(h->lock);
    PyThread_free_lock(h->lock); PyMem_Free(h);
}
static PyObject *create_held(PyObject *self, PyObject *unused) {
    (void)self; (void)unused;
    Held *h = PyMem_Malloc(sizeof(*h));
    if (!h) return PyErr_NoMemory();
    h->held=0; h->lock=PyThread_allocate_lock();
    if (!h->lock) { PyMem_Free(h); return PyErr_NoMemory(); }
    if (!PyThread_acquire_lock(h->lock, NOWAIT_LOCK)) {
        PyThread_free_lock(h->lock); PyMem_Free(h);
        return PyErr_Format(PyExc_RuntimeError,"failed to establish held fixture");
    }
    h->held=1;
    PyObject *p=PyCapsule_New(h,CAPSULE_NAME,destroy_held);
    if (!p) { PyThread_release_lock(h->lock); PyThread_free_lock(h->lock); PyMem_Free(h); }
    return p;
}
static PyObject *trial(PyObject *self, PyObject *args) {
    (void)self;
    PyObject *capsule; const char *mode;
    if (!PyArg_ParseTuple(args,"Os",&capsule,&mode)) return NULL;
    Held *h=PyCapsule_GetPointer(capsule,CAPSULE_NAME);
    if (!h) return NULL;
    int quantum=strcmp(mode,"quantum")==0;
    if (!quantum && strcmp(mode,"full")!=0) return PyErr_Format(PyExc_ValueError,"unknown mode");
    if (!h->held) return PyErr_Format(PyExc_RuntimeError,"fixture not held");
    Wait waits[MAX_WAITS]; int count=0, cap_hit=0, unexpected=0, interrupted=0;
    int policy=0; struct sched_param sched={0};
    int sched_rc=pthread_getschedparam(pthread_self(),&policy,&sched);
    int qos=-1, relative_priority=0;
#ifdef __APPLE__
    qos=(int)pthread_get_qos_class_np(pthread_self(),&relative_priority);
#endif
    unsigned long tid=PyThread_get_thread_ident();
    unsigned long native_id=0;
#ifdef PY_HAVE_THREAD_NATIVE_ID
    native_id=PyThread_get_thread_native_id();
#endif
    /* Establish the single deadline BEFORE dropping the GIL. No setup within it. */
    uint64_t entry=wall_ns(), entry_cpu=cpu_ns(), deadline=entry+BUDGET_NS;
    uint64_t released_entry=0, native_return=0, native_cpu=0, before_reattach=0;
    Py_BEGIN_ALLOW_THREADS
    released_entry=wall_ns();
    for (;;) {
        uint64_t now=wall_ns();
        if (!now || now>=deadline || deadline-now<1000) break;
        if (count==MAX_WAITS) { cap_hit=1; break; }
        uint64_t remaining=deadline-now;
        uint64_t requested=quantum && remaining>QUANTUM_NS ? QUANTUM_NS : remaining;
        /* Public API is integral microseconds; floor, never add residual grace. */
        PY_TIMEOUT_T us=(PY_TIMEOUT_T)(requested/1000);
        Wait *w=&waits[count++]; w->derived=now; w->us=(long long)us;
        w->cpu_enter=cpu_ns(); w->enter=wall_ns();
        w->status=(int)PyThread_acquire_lock_timed(h->lock,us,0);
        w->leave=wall_ns(); w->cpu_leave=cpu_ns();
        if (w->status==PY_LOCK_ACQUIRED) {
            PyThread_release_lock(h->lock); unexpected=1; break;
        }
        if (w->status==PY_LOCK_INTR) { interrupted=1; break; }
    }
    native_return=wall_ns(); native_cpu=cpu_ns();
    before_reattach=wall_ns();
    Py_END_ALLOW_THREADS
    /* First C observation after Py_END_ALLOW_THREADS reattaches this thread. */
    uint64_t after_gil=wall_ns(), after_cpu=cpu_ns();
    if (unexpected) h->held=0;
    PyObject *records=PyList_New(count);
    if (!records) return NULL;
    for (int i=0;i<count;i++) {
        Wait *w=&waits[i];
        PyObject *row=Py_BuildValue("{s:K,s:K,s:K,s:K,s:K,s:L,s:i}",
            "request_derived_ns",(unsigned long long)w->derived,
            "wait_enter_ns",(unsigned long long)w->enter,
            "wait_return_ns",(unsigned long long)w->leave,
            "cpu_enter_ns",(unsigned long long)w->cpu_enter,
            "cpu_return_ns",(unsigned long long)w->cpu_leave,
            "requested_us",w->us,"status",w->status);
        if (!row) { Py_DECREF(records); return NULL; }
        PyList_SET_ITEM(records,i,row);
    }
    PyObject *result=Py_BuildValue("{s:s,s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:i,s:i,s:i,s:i,s:i,s:i,s:i,s:k,s:k,s:N}",
        "mode",mode,"native_entry_ns",(unsigned long long)entry,
        "deadline_ns",(unsigned long long)deadline,
        "released_entry_ns",(unsigned long long)released_entry,
        "native_return_ns",(unsigned long long)native_return,
        "before_gil_reattach_ns",(unsigned long long)before_reattach,
        "after_gil_ns",(unsigned long long)after_gil,
        "entry_cpu_ns",(unsigned long long)entry_cpu,
        "native_return_cpu_ns",(unsigned long long)native_cpu,
        "after_gil_cpu_ns",(unsigned long long)after_cpu,
        "cap_hit",cap_hit,"unexpected_acquisition",unexpected,"interrupted",interrupted,
        "qos_class_raw",qos,"qos_relative_priority",relative_priority,
        "sched_policy",policy,"sched_query_rc",sched_rc,
        "thread_ident",tid,"native_id",native_id,"waits",records);
    if (result) {
        PyObject *priority=PyLong_FromLong(sched.sched_priority);
        if (!priority || PyDict_SetItemString(result,"sched_priority",priority)) {
            Py_XDECREF(priority); Py_DECREF(result); return NULL;
        }
        Py_DECREF(priority);
    }
    return result;
}
static PyObject *metadata(PyObject *self, PyObject *unused) {
    (void)self; (void)unused;
    unsigned long numer=1,denom=1;
    const char *wall="clock_gettime(CLOCK_MONOTONIC)";
#ifdef __APPLE__
    wall="mach_absolute_time()"; numer=timebase.numer; denom=timebase.denom;
#endif
    return Py_BuildValue("{s:s,s:s,s:s,s:s,s:k,s:k,s:i,s:i,s:i,s:i}",
        "api","PyThread_acquire_lock_timed",
        "backend_scope","public legacy PyThread API; not plain Lock/PyMutex; compiled internal backend opaque, not inferred",
        "native_monotonic_clock",wall,"native_thread_cpu_clock","clock_gettime(CLOCK_THREAD_CPUTIME_ID)",
        "mach_timebase_numer",numer,"mach_timebase_denom",denom,
        "py_lock_failure",(int)PY_LOCK_FAILURE,"py_lock_acquired",(int)PY_LOCK_ACQUIRED,
        "py_lock_intr",(int)PY_LOCK_INTR,"max_waits_per_trial",MAX_WAITS);
}
static PyMethodDef methods[]={
    {"create_held",create_held,METH_NOARGS,"Allocate/acquire fixture before worker starts."},
    {"trial",trial,METH_VARARGS,"One fixed 30ms trial; no Python callbacks while GIL detached."},
    {"metadata",metadata,METH_NOARGS,"Explicit public API/clock identity, not guessed internal build flags."},
    {NULL,NULL,0,NULL}
};
static struct PyModuleDef module={PyModuleDef_HEAD_INIT,"_native_phase_probe",NULL,-1,methods,NULL,NULL,NULL,NULL};
PyMODINIT_FUNC PyInit__native_phase_probe(void) {
#ifdef __APPLE__
    if (mach_timebase_info(&timebase)!=KERN_SUCCESS || !timebase.denom)
        return PyErr_Format(PyExc_RuntimeError,"Mach clock initialization failed");
#endif
    if (!wall_ns() || !cpu_ns()) return PyErr_Format(PyExc_RuntimeError,"required clocks unavailable");
    return PyModule_Create(&module);
}
