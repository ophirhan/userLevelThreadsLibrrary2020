#include <iostream>
#include "uthreads.h"
#include <stdio.h>
#include <setjmp.h>
#include <signal.h>
#include <unistd.h>
#include <sys/time.h>
#include <exception>
#include <list>

/**
 * User-Level Threads Library (uthreads)
 * Author: OS, os@cs.huji.ac.il
 */

#define JB_SP 6
#define JB_PC 7
#define SYS_ERROR_MSG "system error: "
#define LIB_ERROR_MSG "thread library error: "
#define MILISECONDS 1000000

/* External interface */
enum State {Ready,Running,Blocked};

typedef unsigned long address_t;



class SimpleThread
{
private:

    int threadQuantCounter;
    int id;
    int priority;
    sigjmp_buf buffer;
    State innerState;
    char stack_t[STACK_SIZE];

public:

    /**
     * Constructs new SimpleThread object
     * @param f  the function the thread points to.
     * @param priority the priority of the thread.
     * @param id the id of the thread.
     */
    SimpleThread(void (*f)(void), int priority, int id):
            threadQuantCounter(0), id(id) ,priority(priority), innerState(Ready)
    {
        address_t sp, pc;
        sp = (address_t)stack_t + STACK_SIZE - sizeof(address_t);
        pc = (address_t)f;
        sigsetjmp(buffer, 1);
        (buffer->__jmpbuf)[JB_SP] = translate_address(sp);
        (buffer->__jmpbuf)[JB_PC] = translate_address(pc);
        sigemptyset(&buffer->__saved_mask);

    }

    /**
     * translates the address
     * @param addr the address to translate
     * @return the translted address
     */
    address_t translate_address(address_t addr)
    {
        address_t ret;
        asm volatile("xor    %%fs:0x30,%0\n"
                     "rol    $0x11,%0\n"
        : "=g" (ret)
        : "0" (addr));
        return ret;
    }

    /**
     * increases the quantumCounter
     */
    void incCounter() {
        ++threadQuantCounter;
    }

    /**
     * sets the inner state of the thread.
     * @param st
     */
    void setSt(State st) {
        SimpleThread::innerState = st;
    }


    /**
     * @return the id of the thread.
     */
    int getId() const {
        return id;
    }

    /**
     * @return the priority of the thread.
     */
    int getPriority() const {
        return priority;
    }

    /**
     * @return the inner state of the thread.
     */
    State getSt() const {
        return innerState;
    }

    /**
     * @return the buffer of the thread.
     */
    __jmp_buf_tag *getBuffer()  {
        return buffer;
    }

    /**
     * @return the quantumCounter of the thread.
     */
    int getThreadCounter() const {
        return threadQuantCounter;
    }

    /**
     * sets the priority of thread.
     * @param priority the desired priority.
     */
    void setPriority(int priority) {
        SimpleThread::priority = priority;
    }

    /**
     * sets the id of the thread.
     * @param id the desired id
     */
    void setId(int id) {
        SimpleThread::id = id;
    }

};
//----------- Globals -------------
// Signal set containing sigvtalrm
static sigset_t sigset1;

// Temporary pointer to hold Simplethread destined to be terminated
static SimpleThread *garbage = nullptr;

// Virtual timer struct
static struct itimerval timer;

// Sigaction struct pointing to schedueler
struct sigaction sa;

// Quantum array, holding time in usecs per priority
static int* quantum;

// Quantum array length
static int maxPrioSize;

// Counts total quantum count
static int quantumCounter;

// General array holding all existing threads by their id
static SimpleThread* threadArray[MAX_THREAD_NUM] = {};

// Organizes in a queue all threads waiting to run by their turn.
static std::list<SimpleThread*> readyQueue;

// The currently running thread.
static SimpleThread* running;



/**
 * Description: This signal handler saves the state of the currently running thread (if it isn't blocked
 * or terminated), finds the next thread to run,
 * sets a virtual timer and switches to the next thread.
 */
void scheduler(int sig);

void freeThreads()
{
    for(auto & i : threadArray){
        if(i != nullptr){
            delete i;
        }
    }
}

/**
 * Description: This function initializes the thread library.
 * You may assume that this function is called before any other thread library
 * function, and that it is called exactly once. The input to the function is
 * an array of the length of a quantum in micro-seconds for each priority.
 * It is an error to call this function with an array containing non-positive integer.
 * size - is the size of the array.
 * Return value: On success, return 0. On failure, return -1.
*/
int uthread_init(int *quantum_usecs, int size)
{
    if(size <= 0)
    {
        std::cerr << LIB_ERROR_MSG << "invalid size value"  << std::endl;
        return -1;
    }
    for(int i = 0; i < size; ++i)
    {
        if(quantum_usecs[i] <= 0)
        {
            std::cerr << LIB_ERROR_MSG << "invalid quantum value"  << std::endl;
            return -1;
        }
    }
    //Sets the signal set

    sigemptyset(&sigset1);
    sigaddset(&sigset1,SIGVTALRM);

    //Initiate global variables

    quantum = quantum_usecs;
    maxPrioSize = size - 1;
    quantumCounter = 0;

    //Sets the main thread as part of the library threads.

    running = new SimpleThread(nullptr,0,0);
    running->setSt(Running);
    threadArray[0] = running;

    //Checks sigaction return value
    sa.sa_handler = &scheduler;
    if (sigaction(SIGVTALRM, &sa, nullptr) < 0) {
        std::cerr << SYS_ERROR_MSG << "sigaction failed" << std::endl;
        freeThreads();
        exit(1);
    }
    scheduler(0);
    return 0;
}

/**
 * Set the new running thread to be the next in the queue.
 * if the queue is empty the running thread remains the same.
 */
void setRunningThread()
{
    if(!readyQueue.empty())
    {
        if((running != nullptr) && (running->getSt() != Blocked))
        {
            readyQueue.push_back(running);
            running->setSt(Ready);
        }
        running  = readyQueue.front();
        running->setSt(Running);
        readyQueue.pop_front();
    }
}

/**
 * Sets a virtual timer for the running thread.
 */
void setTimer()
{
    quantumCounter++;
    running->incCounter();
    int usecs = quantum[running->getPriority()];
    timer.it_value.tv_sec = usecs / MILISECONDS;
    timer.it_value.tv_usec = usecs % MILISECONDS;
    if (setitimer (ITIMER_VIRTUAL, &timer, nullptr)) {
        std::cerr << SYS_ERROR_MSG << "itimer failed" << std::endl;
        freeThreads();
        exit(1);
    }
}

void scheduler(int sig){
    int ret_val = 0;
    if( sig != 0)
    {
        ret_val= sig;
    }
    sa.sa_handler = &scheduler;
    if(running != nullptr) {
        ret_val = sigsetjmp(running->getBuffer(), 1);
    }
    if(ret_val!=0){
        if (sigaction(SIGVTALRM, &sa, nullptr) < 0) {
            std::cerr << SYS_ERROR_MSG << "sigaction failed" << std::endl;
            freeThreads();
            exit(1);
        }
        if(garbage != nullptr)
        {
            delete garbage;
            garbage = nullptr;
        }
        return;
    }
    setRunningThread();
    setTimer();
    siglongjmp(running->getBuffer(),1);
}


/**
 * Description: This function creates a new thread, whose entry point is the
 * function f with the signature void f(void). The thread is added to the end
 * of the READY threads list. The uthread_spawn function should fail if it
 * would cause the number of concurrent threads to exceed the limit
 * (MAX_THREAD_NUM). Each thread should be allocated with a stack of size
 * STACK_SIZE bytes.
 * priority - The priority of the new thread.
 * Return value: On success, return the ID of the created thread.
 * On failure, return -1.
*/
int uthread_spawn(void (*f)(void), int priority)
{
    sigprocmask(SIG_BLOCK,&sigset1, nullptr);
    if((priority > maxPrioSize )|| (priority < 0))
    {
        std::cerr << LIB_ERROR_MSG << "invalid input" << std::endl;
        sigprocmask(SIG_UNBLOCK,&sigset1, nullptr);
        return -1;
    }
    for(int i = 0; i < MAX_THREAD_NUM; ++i)
    {
        if(threadArray[i] == nullptr)
        {
            auto* newThread = new SimpleThread(f,priority,i);
            readyQueue.push_back(newThread);
            threadArray[i] = newThread;
            sigprocmask(SIG_UNBLOCK,&sigset1, nullptr);
            return i;
        }
    }
    std::cerr << LIB_ERROR_MSG << "too many threads" << std::endl;
    sigprocmask(SIG_UNBLOCK,&sigset1, nullptr);
    return -1;
}

/**
 * Description: This function changes the priority of the thread with ID tid.
 * If this is the current running thread, the effect should take place only the
 * next time the thread gets scheduled.
 * Return value: On success, return 0. On failure, return -1.
*/
int uthread_change_priority(int tid, int priority)
{
    if((tid < 0) || (tid >= MAX_THREAD_NUM)||(threadArray[tid] == nullptr))
    {
        std::cerr << LIB_ERROR_MSG << "invalid input" << std::endl;
        return -1;
    }
    threadArray[tid]->setPriority(priority);
    return 0;
}

/**
 * This function deletes the main thread - and frees all the memory allocated for the library
 */
void terminateMainThread()
{
    if (sigaction(SIGVTALRM, &sa, nullptr) < 0) {
        std::cerr << SYS_ERROR_MSG << "sigaction failed" << std::endl;
        freeThreads();
        exit(1);
    }
    freeThreads();
    exit(0);
}

/**
 * This function deletes the current running thread - ignores VT ALARM signal during the process
 * @param tid  - the id of the thread
 * @return 0 upon success. otherwise exits.
 */
int terminateRunningThread(int tid)
{
    if (sigaction(SIGVTALRM, &sa, nullptr) < 0) {
        std::cerr << SYS_ERROR_MSG << "sigaction failed" << std::endl;
        freeThreads();
        exit(1);
    }
    running = nullptr;
    garbage = threadArray[tid];
    threadArray[tid] = nullptr;
    scheduler(0);
    return 0;
}
/**
 * This function deletes a thread which isnot running currently, and isn't the main thread.
 * @param tid - the id of the thread.
 */
void terminateRegularThread(int tid)
{
    sigprocmask(SIG_BLOCK, &sigset1, nullptr);
    readyQueue.remove(threadArray[tid]);
    delete threadArray[tid];
    threadArray[tid] = nullptr;
    sigprocmask(SIG_UNBLOCK,&sigset1,nullptr);
}

/**
 * Description: This function terminates the thread with ID tid and deletes
 * it from all relevant control structures. All the resources allocated by
 * the library for this thread should be released. If no thread with ID tid
 * exists it is considered an error. Terminating the main thread
 * (tid == 0) will result in the termination of the entire process using
 * exit(0) [after releasing the assigned library memory].
 * Return value: The function returns 0 if the thread was successfully
 * terminated and -1 otherwise. If a thread terminates itself or the main
 * thread is terminated, the function does not return.
*/
int uthread_terminate(int tid)
{
    sa.sa_handler = SIG_IGN;
    if(tid == 0)
        terminateMainThread();
    if((tid < 0) || (tid >= MAX_THREAD_NUM)||(threadArray[tid] == nullptr))
    {
        std::cerr << LIB_ERROR_MSG << "invalid input" << std::endl;
        return -1;
    }
    if(threadArray[tid] == running)
    {
        return terminateRunningThread(tid);
    }
    terminateRegularThread(tid);
    return 0;
}


/**
 * Description: This function blocks the thread with ID tid. The thread may
 * be resumed later using uthread_resume. If no thread with ID tid exists it
 * is considered as an error. In addition, it is an error to try blocking the
 * main thread (tid == 0). If a thread blocks itself, a scheduling decision
 * should be made. Blocking a thread in BLOCKED state has no
 * effect and is not considered an error.
 * Return value: On success, return 0. On failure, return -1.
*/
int uthread_block(int tid)
{
    sa.sa_handler = SIG_IGN;
    if((tid <= 0) || (tid >= MAX_THREAD_NUM)||(threadArray[tid] == nullptr))
    {
        std::cerr << LIB_ERROR_MSG << "invalid input" << std::endl;
        return -1;
    }
    if(threadArray[tid] == running)
    {
        if (sigaction(SIGVTALRM, &sa, nullptr) < 0) {
            std::cerr << SYS_ERROR_MSG << "sigaction failed" << std::endl;
            freeThreads();
            exit(1);
        }
        threadArray[tid]->setSt(Blocked);
        scheduler(0);
        return 0;
    }
    if(threadArray[tid]->getSt() == Ready)
    {
        sigset_t before;
        sigemptyset(&before);
        sigprocmask(SIG_BLOCK, &sigset1, &before);
        threadArray[tid]->setSt(Blocked);
        readyQueue.remove(threadArray[tid]);
        sigprocmask(SIG_SETMASK, &before, nullptr);

    }
    return 0;
}


/**
 * Description: This function resumes a blocked thread with ID tid and moves
 * it to the READY state. Resuming a thread in a RUNNING or READY state
 * has no effect and is not considered as an error. If no thread with
 * ID tid exists it is considered an error.
 * Return value: On success, return 0. On failure, return -1.
*/
int uthread_resume(int tid)
{
    if((tid < 0) || (tid >= MAX_THREAD_NUM)||(threadArray[tid] == nullptr))
    {
        std::cerr << LIB_ERROR_MSG << "invalid input" << std::endl;
        return -1;
    }
    if(threadArray[tid]->getSt() == Blocked){
        threadArray[tid]->setSt(Ready);
        readyQueue.push_back(threadArray[tid]);
    }
    return 0;

}


/**
 * Description: This function returns the thread ID of the calling thread.
 * Return value: The ID of the calling thread.
*/
int uthread_get_tid()
{
    return running->getId();
}

/**
 * Description: This function returns the total number of quantums since
 * the library was initialized, including the current quantum.
 * Right after the call to uthread_init, the value should be 1.
 * Each time a new quantum starts, regardless of the reason, this number
 * should be increased by 1.
 * Return value: The total number of quantums.
*/
int uthread_get_total_quantums()
{
    return quantumCounter;
}

/**
 * Description: This function returns the number of quantums the thread with
 * ID tid was in RUNNING state. On the first time a thread runs, the function
 * should return 1. Every additional quantum that the thread starts should
 * increase this value by 1 (so if the thread with ID tid is in RUNNING state
 * when this function is called, include also the current quantum). If no
 * thread with ID tid exists it is considered an error.
 * Return value: On success, return the number of quantums of the thread with ID tid.
 * 			     On failure, return -1.
*/
int uthread_get_quantums(int tid)
{
    if((tid < 0) || (tid >= MAX_THREAD_NUM)||(threadArray[tid] == nullptr))
    {
        std::cerr << LIB_ERROR_MSG << "invalid input" << std::endl;
        return -1;
    }
    return threadArray[tid]->getThreadCounter();
}
