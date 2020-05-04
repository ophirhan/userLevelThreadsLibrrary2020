#include <iostream>
#include "uthreads.h"
#include <stdio.h>
#include <setjmp.h>
#include <signal.h>
#include <unistd.h>
#include <sys/time.h>
#include <exception>
#include <list>
#include <set>

/*
 * User-Level Threads Library (uthreads)
 * Author: OS, os@cs.huji.ac.il
 */

#define MAX_THREAD_NUM 100 /* maximal number of threads */
#define STACK_SIZE 4096 /* stack size per thread (in bytes) */
#define JB_SP 6
#define JB_PC 7
#define SYS_ERROR_MSG "system error: "
#define LIB_ERROR_MSG "thread library error: "

/* External interface */
enum State {Ready,Running,Blocked,Terminated};

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

    SimpleThread(void (*f)(void), int priority, int id):
            priority(priority), innerState(Ready), threadQuantCounter(0), id(id)
    {
        address_t sp, pc;
        sp = (address_t)stack_t + STACK_SIZE - sizeof(address_t);
        pc = (address_t)f;
        sigsetjmp(buffer, 1);
        (buffer->__jmpbuf)[JB_SP] = translate_address(sp);
        (buffer->__jmpbuf)[JB_PC] = translate_address(pc);
        sigemptyset(&buffer->__saved_mask);

    }

    address_t translate_address(address_t addr)
    {
        address_t ret;
        asm volatile("xor    %%fs:0x30,%0\n"
                     "rol    $0x11,%0\n"
        : "=g" (ret)
        : "0" (addr));
        return ret;
    }

    void incCounter() {
        ++threadQuantCounter;
    }

    void setSt(State st) {
        SimpleThread::innerState = st;
    }


    int getId() const {
        return id;
    }

    int getPriority() const {
        return priority;
    }

    State getSt() const {
        return innerState;
    }

    __jmp_buf_tag *getBuffer()  {
        return buffer;
    }

    int getThreadCounter() const {
        return threadQuantCounter;
    }

    void setPriority(int priority) {
        SimpleThread::priority = priority;
    }

    void setId(int id) {
        SimpleThread::id = id;
    }

};
//----------- Globals -------------

static int* quantum;
static int maxPrioSize;
static int quantumCounter;
static SimpleThread* threadArray[MAX_THREAD_NUM] = {};
static std::list<SimpleThread*> readyQueue;
static SimpleThread* running;



void scheduler(int sig);

/*
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
    for(int i = 0; i < size; ++i)
    {
        if(quantum_usecs[i] <= 0)
        {
            std::cerr << LIB_ERROR_MSG << "invalid quantum value"  << std::endl;
            return -1;
        }
    }
    quantum = quantum_usecs;
    maxPrioSize = size - 1;
    quantumCounter = 1;
    running = new SimpleThread(nullptr,0,0);
    running->setSt(Running);
    threadArray[0] = running;
    struct sigaction sa = {nullptr};
    sa.sa_handler = &scheduler;
    if (sigaction(SIGVTALRM, &sa, nullptr) < 0) {
       std::cerr << SYS_ERROR_MSG << "sigaction failed" << std::endl;
       exit(1);
    }
    scheduler(0);
    return 0;
}


void scheduler(int sig){
    int ret_val = 0;
    struct sigaction sa = {nullptr};
    sa.sa_handler = &scheduler;
//    sigset_t sigset_new, sigset_old;
//    sigemptyset(&sigset_new);
//    sigaddset(&sigset_new, SIGVTALRM);
//    sigprocmask(SIG_BLOCK, &sigset_new, &sigset_old);
    if(running != nullptr) {
        ret_val = sigsetjmp(running->getBuffer(), 1);
    }
    if(ret_val!=0){
        if (sigaction(SIGVTALRM, &sa, nullptr) < 0) {
            std::cerr << SYS_ERROR_MSG << "sigaction failed" << std::endl;
            exit(1);
        }
//        sigprocmask(SIG_UNBLOCK, &sigset_new, nullptr);
        return;
    }
    if(!readyQueue.empty())
    {
        if((running != nullptr) && (running->getSt() != Blocked))
        {
            readyQueue.push_back(running);
        }
        running  = readyQueue.front();
        readyQueue.pop_front();
    }

    running->incCounter();
    quantumCounter++;
    static struct itimerval timer;
    timer.it_value.tv_sec = 0;		// first time interval, seconds part
    timer.it_value.tv_usec = quantum[running->getPriority()];
    if (setitimer (ITIMER_VIRTUAL, &timer, NULL)) {
        std::cerr << SYS_ERROR_MSG << "itimer failed" << std::endl;
        exit(1);
    }
    siglongjmp(running->getBuffer(),1);

}

/*
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
    if((priority > maxPrioSize )|| (priority < 0))
    {
        std::cerr << LIB_ERROR_MSG << "invalid input" << std::endl;
        return -1;
    }
    for(int i = 0; i < MAX_THREAD_NUM; ++i)
    {
        if(threadArray[i] == nullptr)
        {
            auto* newThread = new SimpleThread(f,priority,i);
            readyQueue.insert(readyQueue.end(),newThread);
            threadArray[i] = newThread;
            return i;
        }
    }
    return -1;
}


/*
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
}


/*
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
    struct sigaction sa = {nullptr};
    sa.sa_handler = SIG_IGN;
    if(tid == 0)
    {
        if (sigaction(SIGVTALRM, &sa, nullptr) < 0) {
            std::cerr << SYS_ERROR_MSG << "sigaction failed" << std::endl;
            exit(1);
        }
        for(auto & i : threadArray){
            if(i != nullptr){
                delete i;
            }
        }
        exit(0);
    }
    if((tid < 0) || (tid >= MAX_THREAD_NUM)||(threadArray[tid] == nullptr))
    {
        std::cerr << LIB_ERROR_MSG << "invalid input" << std::endl;
        return -1;
    }
    if(threadArray[tid] == running)
    {
        if (sigaction(SIGVTALRM, &sa, nullptr) < 0) {
            std::cerr << SYS_ERROR_MSG << "sigaction failed" << std::endl;
            exit(1);
        }
        running = nullptr;
        delete threadArray[tid];
        threadArray[tid] = nullptr;
        scheduler(0);
        return 0;
    }
    sigset_t sigset1;
    sigemptyset(&sigset1);
    sigaddset(&sigset1,SIGVTALRM);
    sigprocmask(SIG_BLOCK, &sigset1, nullptr);
    readyQueue.remove(threadArray[tid]);
    delete threadArray[tid];
    threadArray[tid] = nullptr;
    sigprocmask(SIG_UNBLOCK,&sigset1,nullptr);
    return 0;
}


/*
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
    struct sigaction sa = {nullptr};
    sa.sa_handler = SIG_IGN;
    if((tid <= 0) || (tid >= MAX_THREAD_NUM)||(threadArray[tid] == nullptr))
    {
        return -1;
    }
    if(threadArray[tid] == running)
    {
        sigaction(SIGVTALRM, &sa, nullptr);
        threadArray[tid]->setSt(Blocked);
        scheduler(0);
    }
    if(threadArray[tid]->getSt() == Ready)
    {
        threadArray[tid]->setSt(Blocked);
        readyQueue.remove(threadArray[tid]);
    }

}


/*
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
        readyQueue.insert(readyQueue.begin(),threadArray[tid]);
    }
    return 0;

}


/*
 * Description: This function returns the thread ID of the calling thread.
 * Return value: The ID of the calling thread.
*/
int uthread_get_tid()
{
    return running->getId();
}


/*
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

/*
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
